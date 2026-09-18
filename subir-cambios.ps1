# subir-cambios.ps1
# Un solo comando para subir cambios al repo sin chocar con los commits
# automáticos del bot diario (.github/workflows/daily_scrape.yml).
#
# Uso:
#   .\subir-cambios.ps1 "Agrega retailer X"
#
# Por qué el orden cambió (commit ANTES de pull, no después):
#   docs/dashboard_data.json lo regenera el bot todos los días, y también lo
#   regeneras tú al probar el dashboard en tu compu -- las dos versiones casi
#   nunca son idénticas byte a byte. Si haces "pull" con ese archivo modificado
#   sin commitear, Git se niega a traer nada ("local changes would be
#   overwritten by merge") y ahí se traba todo. Commiteando primero, ese
#   archivo deja de estar "sin commitear" y el pull se puede resolver solo.
#
#   Además, para ESE archivo puntual (que se regenera solo, no se edita a
#   mano), configuramos a Git para que en caso de choque con el commit del
#   bot, se quede con tu versión y siga -- así nunca más se traba el push por
#   esto. El resto de archivos (código, retailers.json, etc.) se mergean
#   normal.
#
# data/precios.db (la base de datos SQLite) es distinto: es binario, así que
# Git no lo puede mezclar como texto. Si vos corriste "py run.py --retailer X"
# en tu compu el mismo día que corrió el bot en GitHub, las dos versiones
# chocan de verdad.
#
# IMPORTANTE (corregido 18/09/2026): antes esto se resolvía quedándose con la
# versión de GitHub sin más -- pero descubrimos que GitHub Actions no puede
# traer datos de Falabella/PlazaVea/Promart/Oechsle (posible bloqueo de IP de
# nube), mientras que corriendo el mismo código desde tu compu SÍ funciona.
# Quedarse con la versión de GitHub a ciegas borraba justo esas capturas
# buenas de tu compu (y con ellas, los datos de Sany, que solo aparece como
# vendedor dentro de Falabella). Ahora el script SUMA las dos versiones con
# merge_precios_db.py en vez de descartar una -- ninguna fila real se pierde,
# venga de tu compu o del bot.
#
# Qué hace, en orden:
#   1. Configura el driver de merge "ours" (una sola vez, no hace nada si ya
#      está configurado) y agrega/actualiza .gitattributes si hace falta.
#   2. git add .    -> agrega tus cambios locales
#   3. git commit   -> los commitea (si no hay nada que commitear, avisa y sigue)
#   4. git pull     -> trae los commits del bot; docs/dashboard_data.json se
#      resuelve solo a favor de tu versión si choca, data/precios.db se
#      SUMA (no se descarta ninguna) si choca, el resto mergea normal
#   5. git push     -> sube todo junto
#
# Si el script se detiene con "ERROR", léelo -- significa que algo real pasó
# (conflicto en un archivo de código, sin internet, etc.) y hace falta mirarlo
# a mano antes de seguir. No vuelvas a correr el script encima sin resolverlo.

param(
    [Parameter(Mandatory = $true)]
    [string]$Mensaje
)

$ErrorActionPreference = "Continue"

Write-Host "0/4 Preparando reglas de merge (una sola vez)..." -ForegroundColor Cyan
git config merge.ours.driver true | Out-Null

Write-Host "1/4 Agregando tus cambios..." -ForegroundColor Cyan
git add .

Write-Host "2/4 Creando commit..." -ForegroundColor Cyan
git commit -m "$Mensaje"
if ($LASTEXITCODE -ne 0) {
    Write-Host "   (No había nada nuevo que commitear -- seguimos igual)" -ForegroundColor Yellow
}

Write-Host "3/4 Trayendo cambios del repo (incluye commits del bot si los hay)..." -ForegroundColor Cyan
git pull --no-edit
if ($LASTEXITCODE -ne 0) {
    # data/precios.db es binario (SQLite) -- Git no puede mezclar dos
    # versiones línea por línea como con texto, así que CUALQUIER choque ahí
    # (vos corriste "py run.py --retailer X" en tu compu el mismo día que
    # corrió el bot en GitHub) sale como conflicto real, aunque el resto del
    # commit esté perfecto. En vez de quedarnos con una sola versión (lo que
    # borraría en silencio capturas reales del lado descartado), sumamos las
    # dos con merge_precios_db.py -- la restricción UNIQUE de la tabla evita
    # duplicados, así que no hay riesgo de "duplicar" precios.
    $conflictos = git diff --name-only --diff-filter=U
    if ($conflictos -and ($conflictos.Trim() -eq "data/precios.db")) {
        Write-Host "   Conflicto solo en data/precios.db (normal si probaste retailers en tu compu hoy)." -ForegroundColor Yellow
        Write-Host "   Sumando tu version y la de GitHub (no se descarta ninguna fila)..." -ForegroundColor Yellow

        # OJO: se usa "cmd /c" para el ">" a propósito -- el redireccionamiento
        # nativo de PowerShell reinterpreta la salida como texto y corrompe
        # un archivo binario como un .db de SQLite. cmd.exe lo deja tal cual.
        cmd /c "git show :2:data/precios.db > precios_ours_temp.db"
        cmd /c "git show :3:data/precios.db > precios_theirs_temp.db"

        py merge_precios_db.py precios_ours_temp.db precios_theirs_temp.db data/precios.db
        $mergeOk = ($LASTEXITCODE -eq 0)

        Remove-Item -ErrorAction SilentlyContinue precios_ours_temp.db, precios_theirs_temp.db

        if (-not $mergeOk) {
            Write-Host "ERROR: merge_precios_db.py falló. Revisa que tengas Python instalado (py) y vuelve a intentar." -ForegroundColor Red
            Write-Host "Mientras tanto, el merge quedó a medias -- corre 'git status' antes de tocar nada más." -ForegroundColor Red
            exit 1
        }

        git add data/precios.db
        git commit --no-edit
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: no se pudo cerrar el merge de data/precios.db. Corre 'git status' y revisa a mano." -ForegroundColor Red
            exit 1
        }
    } else {
        Write-Host "ERROR: el pull falló con un conflicto real (no solo en data/precios.db)." -ForegroundColor Red
        Write-Host "Revisa el mensaje de arriba, resuelve el conflicto a mano, y recién ahí vuelve a correr el script." -ForegroundColor Red
        exit 1
    }
}

Write-Host "4/4 Subiendo a GitHub..." -ForegroundColor Cyan
git push
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: el push falló. No se subió nada -- revisa el mensaje de arriba." -ForegroundColor Red
    exit 1
}

Write-Host "Listo." -ForegroundColor Green
