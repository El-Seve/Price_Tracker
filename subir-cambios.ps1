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
# Qué hace, en orden:
#   1. Configura el driver de merge "ours" (una sola vez, no hace nada si ya
#      está configurado) y agrega/actualiza .gitattributes si hace falta.
#   2. git add .    -> agrega tus cambios locales
#   3. git commit   -> los commitea (si no hay nada que commitear, avisa y sigue)
#   4. git pull     -> trae los commits del bot; docs/dashboard_data.json se
#      resuelve solo a favor de tu versión si choca, el resto mergea normal
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
git pull
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: el pull falló con un conflicto real (no en dashboard_data.json)." -ForegroundColor Red
    Write-Host "Revisa el mensaje de arriba, resuelve el conflicto a mano, y recién ahí vuelve a correr el script." -ForegroundColor Red
    exit 1
}

Write-Host "4/4 Subiendo a GitHub..." -ForegroundColor Cyan
git push
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: el push falló. No se subió nada -- revisa el mensaje de arriba." -ForegroundColor Red
    exit 1
}

Write-Host "Listo." -ForegroundColor Green
