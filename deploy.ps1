<#
.SYNOPSIS
    Deploy Automatizado de Alta Performance (Windows -> WSL Nativo -> Azure)
    Resolve o problema de lentidão de disco copiando o projeto para o Linux antes do build.
#>

# --- CONFIGURAÇÃO ---
$AppName = "see-d-crm-ingestaobot"      # Nome exato da sua Function no Azure
$LinuxTargetDir = "~/deploy_temp_bot"   # Pasta temporária que será criada dentro do Linux

Clear-Host
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "   DEPLOY AUTOMATIZADO VIA WSL (FAST)     " -ForegroundColor Cyan
Write-Host "   Alvo: $AppName                         " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. LIMPEZA NO WINDOWS (Para não copiar lixo desnecessário)
Write-Host "`n[1/4] Limpando pasta Windows..." -ForegroundColor Yellow
$lixo = @(".python_packages", ".venv", ".venv_linux", "__pycache__", "bin", "obj")
foreach ($item in $lixo) {
    if (Test-Path $item) { 
        Remove-Item -Path $item -Recurse -Force -ErrorAction SilentlyContinue 
    }
}

# 2. CONVERTER CAMINHO WINDOWS -> LINUX
# Transforma "C:\Users\..." em "/mnt/c/Users/..." para o Linux entender
$WinPath = Get-Location
$WslSourcePath = "/mnt/c" + $WinPath.Path.Substring(2).Replace('\', '/')
Write-Host "      Origem Windows: $WslSourcePath" -ForegroundColor Gray

# 3. COMANDO MÁGICO DO WSL
# Este bloco cria um comando Bash único que faz tudo no Linux de uma vez
Write-Host "`n[2/4] Preparando ambiente Linux (Nativo)..." -ForegroundColor Yellow

$BashScript = "
echo '--> [Linux] Limpando ambiente antigo...'
rm -rf $LinuxTargetDir
mkdir -p $LinuxTargetDir

echo '--> [Linux] Copiando arquivos do Windows (Isso evita o travamento)...'
cp -r '$WslSourcePath/'* $LinuxTargetDir/

echo '--> [Linux] Entrando na pasta...'
cd $LinuxTargetDir

echo '--> [Linux] Criando Virtual Environment...'
python3 -m venv .venv
source .venv/bin/activate

echo '--> [Linux] Instalando Dependências (pip)...'
pip install -r requirements.txt

echo '--> [Linux] INICIANDO PUBLICAÇÃO NO AZURE...'
# Aqui usamos --build local porque estamos 'localmente' no Linux
func azure functionapp publish $AppName --build local
"

# 4. EXECUÇÃO
Write-Host "`n[3/4] Executando Build e Deploy no WSL..." -ForegroundColor Yellow
Write-Host "      (Isso vai levar segundos, não minutos)..." -ForegroundColor Gray
Write-Host "------------------------------------------------------" -ForegroundColor DarkGray

# Chama o WSL e passa o script gigante acima
wsl --exec bash -c $BashScript

# 5. RESULTADO
if ($LASTEXITCODE -eq 0) {
    Write-Host "`n==========================================" -ForegroundColor Green
    Write-Host "   SUCESSO! Deploy Concluído." -ForegroundColor Green
    Write-Host "==========================================" -ForegroundColor Green
} else {
    Write-Host "`n==========================================" -ForegroundColor Red
    Write-Host "   FALHA! Algo deu errado no comando Linux." -ForegroundColor Red
    Write-Host "==========================================" -ForegroundColor Red
}

Read-Host -Prompt "Pressione Enter para sair"