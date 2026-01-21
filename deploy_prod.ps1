<#
.SYNOPSIS
    [PRODUÇÃO] Deploy Automatizado de Alta Performance (Windows -> WSL Nativo -> Azure)
    ATENÇÃO: Este script publica diretamente no ambiente de PRODUÇÃO.
#>

# --- CONFIGURAÇÃO DE PRODUÇÃO ---
# 1. Mude este nome para o nome exato da sua Function de Produção (ex: see-p-crm-ingestaobot)
$AppName = "see-p-crm-ingestaobot"    

# 2. Pasta temporária isolada para Prod
$LinuxTargetDir = "~/deploy_prod_bot"   

Clear-Host
Write-Host "==========================================" -ForegroundColor Red
Write-Host "      DEPLOY EM PRODUÇÃO (WSL)            " -ForegroundColor Red
Write-Host "      Alvo: $AppName                      " -ForegroundColor White
Write-Host "==========================================" -ForegroundColor Red

# --- TRAVA DE SEGURANÇA ---
Write-Host "VOCÊ ESTÁ PRESTES A PUBLICAR EM PRODUÇÃO." -ForegroundColor Yellow
Write-Host "Isso irá sobrescrever a versão ativa."
$confirm = Read-Host "Digite 'PROD' para confirmar e continuar"

if ($confirm -ne "PROD") {
    Write-Host "Operação cancelada pelo usuário." -ForegroundColor Gray
    exit
}

# 1. LIMPEZA NO WINDOWS (Garante que não envia lixo local)
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

# Script Bash ajustado para Produção
$BashScript = @"
set -e

# Garante que estamos logados (opcional, remove se já estiver garantido)
# az account show > /dev/null 2>&1 || { echo 'Erro: Faça az login no WSL primeiro'; exit 1; }

echo '--> [Linux] Limpando ambiente de build PROD...'
rm -rf $LinuxTargetDir
mkdir -p $LinuxTargetDir

echo '--> [Linux] Copiando arquivos limpos...'
cp -r "$WslSourcePath/"* $LinuxTargetDir/

echo '--> [Linux] Entrando na pasta...'
cd $LinuxTargetDir

echo '--> [Linux] Criando VENV isolado...'
python3 -m venv .venv
source .venv/bin/activate

echo '--> [Linux] Instalando Dependências...'
pip install -r requirements.txt

echo '--> [Linux] PUBLICANDO EM PRODUÇÃO ($AppName)...'
# --build local: Garante que as bibliotecas Python sejam compiladas no Linux (WSL) antes de subir
func azure functionapp publish $AppName --build local --force
"@

# --- CORREÇÃO DE QUEBRA DE LINHA (CRLF -> LF) ---
$BashScriptClean = $BashScript.Replace("`r", "")

# 4. EXECUÇÃO
Write-Host "`n[3/4] Executando Build e Deploy no WSL..." -ForegroundColor Yellow
Write-Host "------------------------------------------------------" -ForegroundColor DarkGray

# Executa o script
wsl --exec bash -c "$BashScriptClean"

# 5. RESULTADO
if ($LASTEXITCODE -eq 0) {
    Write-Host "`n==========================================" -ForegroundColor Green
    Write-Host "   SUCESSO! Deploy em PRODUÇÃO Concluído." -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Green
} else {
    Write-Host "`n==========================================" -ForegroundColor Red
    Write-Host "   FALHA! Ocorreu um erro no Deploy." -ForegroundColor Red
    Write-Host "==========================================" -ForegroundColor Red
}

Read-Host -Prompt "Pressione Enter para sair"