import zipfile
import os
import shutil
import subprocess
import sys

ZIP_NAME = "deploy.zip"

# Pastas para ignorar (NÃO queremos enviar lixo do Windows)
IGNORE_DIRS = {'.git', '.vscode', '.venv', 'env', '__pycache__', '.idea', 'bin', 'lib', 'include', 'Scripts'}
IGNORE_FILES = {ZIP_NAME, 'build.py', 'deploy_prod.ps1', 'deploy_dev_emergency.ps1'}

def install_deps_locally():
    """Baixa as bibliotecas para uma pasta local antes de zipar"""
    print("⬇️  Baixando bibliotecas localmente...")
    
    # Esta é a estrutura EXATA que o Azure exige para Python
    target_dir = os.path.join(os.getcwd(), ".python_packages", "lib", "site-packages")
    
    # Limpa instalação anterior
    if os.path.exists(target_dir): shutil.rmtree(os.path.join(os.getcwd(), ".python_packages"))
    os.makedirs(target_dir, exist_ok=True)
    
    # Instala usando o pip do sistema
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", 
        "-r", "requirements.txt", 
        "-t", target_dir
    ])
    print("✅ Bibliotecas baixadas com sucesso!")

def create_zip():
    # 1. Instala dependências
    install_deps_locally()
    
    # 2. Cria o ZIP
    print(f"📦 Criando {ZIP_NAME} com pacote completo...")
    if os.path.exists(ZIP_NAME): os.remove(ZIP_NAME)

    count = 0
    with zipfile.ZipFile(ZIP_NAME, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk('.'):
            # Remove pastas ignoradas
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                if file in IGNORE_FILES or file.endswith(('.log', '.pyc')): continue
                
                full_path = os.path.join(root, file)
                # Corrige barras para Linux
                arcname = os.path.relpath(full_path, '.').replace(os.sep, '/')
                zf.write(full_path, arcname)
                count += 1
                
    print(f"✅ ZIP PRONTO! ({count} arquivos inclusos)")

if __name__ == "__main__":
    create_zip()