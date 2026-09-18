# subir-cambios.ps1
# Un solo comando para subir cambios al repo sin chocar con los commits
# automáticos del bot diario (.github/workflows/daily_scrape.yml).
#
# Uso:
#   .\subir-cambios.ps1 "Agrega retailer X"
#
# CAMBIO IMPORTANTE (corregido 18/09/2026): docs/dashboard_data.json YA NO se
# sube "tal cual está en tu disco" -- se REGENERA siempre, como último paso,
# a partir de la base de datos ya fusionada (data/precios.db), justo antes de
# subir. Antes el script tenía una regla ("merge=ours") que en caso de choque
# con el commit del bot se quedaba con la versión que vos ya tenías commiteada
# -- el problema es que la mayoría de tus despliegues (código nuevo, sin tocar
# datos) commitean docs/dashboard_data.json SIN haberlo regenerado, así que
# "tu versión" muchas veces era una captura vieja de días atrás. Cuando esa
# versión vieja le ganaba el choque a la fresca del bot, el dashboard volvía
# atrás en el tiempo sin que nadie lo pidiera (así se descubrió el bug: la
# pestaña Sany volvió a mostrar "2026-09-07" después de haberse arreglado).
#
# La solución de fondo: dashboard_data.json es un archivo 100% calculado a
# partir de data/precios.db -- no tiene sentido "elegir cuál versión gana" en
# un choque, tiene sentido recalcularlo siempre desde la fuente de verdad
# (la base de datos, que sí se fusiona de verdad con merge_precios_db.py). Por
# eso ahora el script lo regenera SIEMPRE en el paso 5, tengas o no un choque.
#
# data/precios.db (la base de datos SQLite) es binario, así que Git no lo
# puede mezclar como texto. Si vos corriste "py run.py --retailer X" en tu
# compu el mismo día que corrió el bot en GitHub, las dos versiones chocan de
# verdad -- en vez de quedarnos con una sola (lo que borraría en silencio
# capturas reales del lado descartado, como pasó con Falabella/Sany antes de
# este fix), las SUMAMOS con merge_precios_db.py. La restricción UNIQUE de la
# tabla evita duplicados, así que no hay riesgo de "duplicar" precios.
#
# Qué hace, en orden:
#   1. Configura el driver de merge "ours" (una sola vez) -- solo sirve ahora
#      para que el "git pull" no se trabe si docs/dashboard_data.json choca;
#      no importa cuál versión "gane" ahí porque el paso 5 lo regenera igual.
#   2. git add . + git commit -> tus cambios de código/config quedan guardados
#   3. git pull  -> trae los commits del bot; data/precios.db se SUMA (no se
#      descarta ninguna fila) si choca; el resto mergea normal
#   4. (nada especial -- ver paso 5)
#   5. Regenera docs/dashboard_data.json desde data/precios.db YA fusionado, y
#      si cambió algo lo commitea aparte
#   6. git push -> sube todo junto
#
# Si el script se detiene con "ERROR", léelo -- significa que algo real pasó
# (conflicto en un archivo de código, sin internet, etc.) y hace falta mirarlo
# a mano antes de seguir. No vuelvas a correr el script encima sin resolverlo.

param(
    [Parameter(Mandatory = $true)]
    [string]$Mensaje
)

$ErrorActionPreference = "Continue"

Write-Host "1/5 Preparando reglas de merge (una sola vez)..." -ForegroundColor Cyan
git config merge.ours.driver true | Out-Null

Write-Host "2/5 Agregando y commiteando tus cambios..." -ForegroundColor Cyan
git add .
git commit -m "$Mensaje"
if ($LASTEXITCODE -ne 0) {
    Write-Host "   (No había nada nuevo que commitear -- seguimos igual)" -ForegroundColor Yellow
}

Write-Host "3/5 Trayendo cambios del repo (incluye commits del bot si los hay)..." -ForegroundColor Cyan
git pull --no-edit
if ($LASTEXITCODE -ne 0) {
    # data/precios.db es binario -- Git no puede mezclar dos versiones línea
    # por línea como con texto, así que CUALQUIER choque ahí (vos corriste
    # "py run.py --retailer X" en tu compu el mismo día que corrió el bot en
    # GitHub) sale como conflicto real, aunque el resto del commit esté
    # perfecto. Sumamos las dos con merge_precios_db.py en vez de descartar
    # una.
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

Write-Host "4/5 Regenerando docs/dashboard_data.json desde la base ya fusionada..." -ForegroundColor Cyan
py -m dashboard.build_dashboard_data
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: no se pudo regenerar dashboard_data.json. Revisa el mensaje de arriba." -ForegroundColor Red
    Write-Host "Tus cambios de código YA están commiteados -- podés corregir el problema y volver a correr el script." -ForegroundColor Red
    exit 1
}
git add docs/dashboard_data.json
git commit -m "Actualizar dashboard_data.json (regenerado automáticamente)" | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "   (dashboard_data.json no cambió -- seguimos igual)" -ForegroundColor Yellow
}

Write-Host "5/5 Subiendo a GitHub..." -ForegroundColor Cyan
git push
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: el push falló. No se subió nada -- revisa el mensaje de arriba." -ForegroundColor Red
    exit 1
}

Write-Host "Listo." -ForegroundColor Green
