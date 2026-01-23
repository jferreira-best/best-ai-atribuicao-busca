<#
.SYNOPSIS
    [PRODUÇÃO] Deploy NATIVO WINDOWS (Ignora o Linux/WSL)
    Usa o login do Windows para enviar o código.
#>

$AppName = "see-p-crm-ingestaobot"
$ZipPath = "$PWD\deploy.zip"

Clear-Host
Write-Host "==========================================" -ForegroundColor Red
Write-Host "      DEPLOY VIA WINDOWS (SEM LINUX)      " -ForegroundColor Red
Write-Host "      Alvo: $AppName                      " -ForegroundColor White
Write-Host "==========================================" -ForegroundColor Red

# --- TRAVA DE SEGURANÇA ---
if ((Read-Host "Digite 'PROD' para confirmar") -ne "PROD") { exit }

# 1. VERIFICAR LOGIN AZURE (No Windows)
Write-Host "`n[1/5] Verificando Login..." -ForegroundColor Yellow
try {
    # Tenta listar grupos para ver se o token está vivo
    $null = az group list --output none 2>&1
} catch {
    Write-Host "Token expirado ou não encontrado. Iniciando login..." -ForegroundColor Yellow
    # Força o login via código (mais seguro contra bloqueios de SSO)
    az login --tenant 16b87798-4517-442c-9200-ce1cca93259c --use-device-code
}

# 2. LIMPEZA
Write-Host "`n[2/5] Limpando arquivos temporários..." -ForegroundColor Yellow
$lixo = @(".python_packages", ".venv", "__pycache__", "bin", "obj", "deploy.zip")
foreach ($item in $lixo) { 
    if (Test-Path $item) { Remove-Item -Path $item -Recurse -Force -ErrorAction SilentlyContinue } 
}

# 3. IDENTIFICAR RESOURCE GROUP
Write-Host "`n[3/5] Buscando Resource Group..." -ForegroundColor Yellow
# Usamos cmd /c para evitar problemas de aspas do PowerShell
$RG = cmd /c "az functionapp list --query ""[?name=='$AppName'].resourceGroup"" -o tsv"
if (-not $RG) {
    Write-Host "ERRO: App '$AppName' não encontrado no Azure. Verifique se a conta está correta." -ForegroundColor Red
    exit
}
Write-Host "    Grupo encontrado: $RG" -ForegroundColor Green

# 4. CRIAR ZIP (PowerShell Nativo)
Write-Host "`n[4/5] Compactando projeto..." -ForegroundColor Yellow
$exclude = @(".git", ".vscode", ".venv", "__pycache__", "deploy_prod.ps1", "*.zip")
Get-ChildItem -Path . -Exclude $exclude | Compress-Archive -DestinationPath $ZipPath -Force

# 5. CONFIGURAR E ENVIAR
Write-Host "`n[5/5] Enviando para o Azure..." -ForegroundColor Yellow

# Configura Build Remoto
cmd /c "az functionapp config appsettings set -g $RG -n $AppName --settings SCM_DO_BUILD_DURING_DEPLOYMENT=true ENABLE_ORYX_BUILD=true --output none"

# Envia o ZIP
cmd /c "az functionapp deployment source config-zip -g $RG -n $AppName --src deploy.zip"

# Limpeza final
Remove-Item $ZipPath -ErrorAction SilentlyContinue

Write-Host "`n==========================================" -ForegroundColor Green
Write-Host "   SUCESSO! Deploy finalizado via Windows." -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Read-Host "Pressione Enter para sair"