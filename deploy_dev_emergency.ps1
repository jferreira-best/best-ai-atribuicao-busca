# ================= CONFIGURACOES =================
$ResourceGroup = "RG-SEE-D-FUNCTION"
$AppName       = "see-d-crm-ingestaobot"
$ZipName       = "deploy.zip"
# =================================================

Clear-Host
Write-Host ">>> DEPLOY 'MARMITA PRONTA' (BUILD LOCAL) <<<" -ForegroundColor Cyan

# 1. GERAR ZIP COMPLETO (Código + Bibliotecas)
Write-Host "1. Preparando pacote..." -ForegroundColor Yellow
python build.py

if (-not (Test-Path $ZipName)) {
    Write-Host "ERRO: O arquivo $ZipName nao foi criado." -ForegroundColor Red; exit
}

# 2. CONFIGURAR AZURE PARA NÃO CONSTRUIR
Write-Host "2. Configurando Azure..." -ForegroundColor Yellow
# Desliga o Oryx Build para aceitar nosso pacote local
az functionapp config appsettings set -g $ResourceGroup -n $AppName --settings SCM_DO_BUILD_DURING_DEPLOYMENT=false ENABLE_ORYX_BUILD=false --output none

# 3. FAZER O UPLOAD
Write-Host "3. Enviando pacote completo..." -ForegroundColor Cyan
# Note: SEM "--build-remote true"
az functionapp deployment source config-zip -g $ResourceGroup -n $AppName --src $ZipName

# 4. REINICIAR O BOT
Write-Host "4. Reiniciando..." -ForegroundColor Yellow
az functionapp restart -g $ResourceGroup -n $AppName --output none

Write-Host "-----------------------------------" -ForegroundColor Green
Write-Host "SUCESSO! Aguarde 1 minuto e teste o bot." -ForegroundColor Green