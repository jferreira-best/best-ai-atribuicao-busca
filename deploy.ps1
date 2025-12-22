<#
.SYNOPSIS
    Deploy Automatizado de Alta Performance (Windows -> WSL Nativo -> Azure)
    CORREÇÃO: Remove caracteres Windows (CR) para evitar erros no Linux Bash.
#>

# --- CONFIGURAÇÃO ---
$AppName = "see-d-crm-ingestaobot"      # Nome exato da sua Function no Azure
$LinuxTargetDir = "~/deploy_temp_bot"   # Pasta temporária dentro do Linux

Clear-Host
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   DEPLOY AUTOMATIZADO VIA WSL (FIXED)    " -ForegroundColor Cyan
Write-Host "   Alvo: $AppName                         " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. LIMPEZA NO WINDOWS
Write-Host "`n[1/4] Limpando pasta Windows..." -ForegroundColor Yellow
$lixo = @(".python_packages", ".venv", ".venv_linux", "__pycache__", "bin", "obj")
foreach ($item in $lixo) {
    if (Test-Path $item) { 
        Remove-Item -Path $item -Recurse -Force -ErrorAction SilentlyContinue 
    }
}

# 2. CONVERTER CAMINHO
$WinPath = Get-Location
$WslSourcePath = "/mnt/c" + $WinPath.Path.Substring(2).Replace('\', '/')
Write-Host "      Origem Windows: $WslSourcePath" -ForegroundColor Gray

# 3. COMANDO MÁGICO DO WSL (SCRIPT BASH)
Write-Host "`n[2/4] Preparando ambiente Linux (Nativo)..." -ForegroundColor Yellow

# Nota: Usamos aspas simples em 'EOF' para evitar que o PowerShell tente interpretar variáveis $ no Bash
$BashScript = @"
set -e
echo '--> [Linux] Limpando ambiente antigo...'
rm -rf $LinuxTargetDir
mkdir -p $LinuxTargetDir

echo '--> [Linux] Copiando arquivos...'
cp -r "$WslSourcePath/"* $LinuxTargetDir/

echo '--> [Linux] Entrando na pasta...'
cd $LinuxTargetDir

echo '--> [Linux] Criando VENV...'
python3 -m venv .venv
source .venv/bin/activate

echo '--> [Linux] Instalando Deps...'
pip install -r requirements.txt

echo '--> [Linux] Publicando...'
func azure functionapp publish $AppName --build local --force
"@

# --- A CORREÇÃO MÁGICA ESTÁ AQUI EMBAIXO ---
# Removemos o Carriage Return (`r) do Windows, deixando apenas o Line Feed (`n) do Linux
$BashScriptClean = $BashScript.Replace("`r", "")

# 4. EXECUÇÃO
Write-Host "`n[3/4] Executando Build e Deploy no WSL..." -ForegroundColor Yellow
Write-Host "------------------------------------------------------" -ForegroundColor DarkGray

# Executa o script limpo
wsl --exec bash -c "$BashScriptClean"

# 5. RESULTADO
if ($LASTEXITCODE -eq 0) {
    Write-Host "`n==========================================" -ForegroundColor Green
    Write-Host "   SUCESSO! Deploy Concluído." -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Green
} else {
    Write-Host "`n==========================================" -ForegroundColor Red
    Write-Host "   FALHA! Ocorreu um erro." -ForegroundColor Red
    Write-Host "==========================================" -ForegroundColor Red
}

Read-Host -Prompt "Pressione Enter para sair"