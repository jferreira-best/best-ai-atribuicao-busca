# ================= CONFIGURACOES =================
$ResourceGroup = "RG-SEE-D-FUNCTION"
$AppName       = "see-d-crm-ingestaobot"
$ZipName       = "deploy.zip"
# =================================================

Clear-Host
Write-Host ">>> DEPLOY GOD MODE (LINUX ON WINDOWS) <<<" -ForegroundColor Cyan

# 1. GERAR ZIP COM LIBS LINUX
Write-Host "1. Baixando versoes Linux e Zipando..." -ForegroundColor Yellow
python build.py

# 2. CONFIGURAR AZURE PARA RODAR O PACOTE (SEM BUILD)
Write-Host "2. Configurando Azure para execução direta..." -ForegroundColor Yellow
# Desativa Oryx, Ativa Run From Package
az functionapp config appsettings set -g $ResourceGroup -n $AppName --settings SCM_DO_BUILD_DURING_DEPLOYMENT=false ENABLE_ORYX_BUILD=false WEBSITE_RUN_FROM_PACKAGE=1 --output none

# 3. UPLOAD DIRETO
Write-Host "3. Enviando pacote blindado..." -ForegroundColor Cyan
az functionapp deployment source config-zip -g $ResourceGroup -n $AppName --src $ZipName

# 4. REINICIAR
Write-Host "4. Reiniciando..." -ForegroundColor Yellow
az functionapp restart -g $ResourceGroup -n $AppName --output none

Write-Host "-----------------------------------" -ForegroundColor Green
Write-Host "SUCESSO! Aguarde 1 min e teste." -ForegroundColor Green