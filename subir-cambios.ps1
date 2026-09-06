# subir-cambios.ps1
# Un solo comando para subir cambios al repo sin chocar con los commits
# automáticos del bot diario (.github/workflows/daily_scrape.yml).
#
# Uso:
#   .\subir-cambios.ps1 "Agrega retailer X"
#
# Qué hace, en orden (el orden es lo que evita el "fetch first" / "rejected"):
#   1. git pull   -> trae primero cualquier commit del bot que no tengas
#   2. git add .  -> agrega tus cambios locales
#   3. git commit -> los commitea (si no hay nada que commitear, avisa y sigue)
#   4. git push   -> sube todo junto

param(
    [Parameter(Mandatory = $true)]
    [string]$Mensaje
)

Write-Host "1/4 Trayendo cambios del repo (incluye commits del bot si los hay)..." -ForegroundColor Cyan
git pull

Write-Host "2/4 Agregando tus cambios..." -ForegroundColor Cyan
git add .

Write-Host "3/4 Creando commit..." -ForegroundColor Cyan
git commit -m "$Mensaje"
if ($LASTEXITCODE -ne 0) {
    Write-Host "   (No había nada nuevo que commitear -- seguimos igual)" -ForegroundColor Yellow
}

Write-Host "4/4 Subiendo a GitHub..." -ForegroundColor Cyan
git push

Write-Host "Listo." -ForegroundColor Green