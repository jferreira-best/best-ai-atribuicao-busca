import zipfile
import os
import shutil
import subprocess
import sys

ZIP_NAME = "deploy.zip"
# Note que tirei .python_packages da ignore list e mudei o alvo
IGNORE_DIRS = {'.git', '.vscode', '.venv', 'env', '__pycache__', '.idea', 'bin', 'lib', 'include', 'Scripts'}
IGNORE_FILES = {ZIP_NAME, 'build.py', 'deploy_prod.ps1', 'deploy_dev_emergency.ps1'}

# NOME DA PASTA DE LIBS (Sem ponto na frente para evitar ser ignorada)
LIB_FOLDER = "_libs"

def install_linux_deps():
    print(f"⬇️  Baixando bibliotecas LINUX para pasta '{LIB_FOLDER}'...")
    
    target_dir = os.path.join(os.getcwd(), LIB_FOLDER, "site-packages")
    
    if os.path.exists(os.path.join(os.getcwd(), LIB_FOLDER)): 
        shutil.rmtree(os.path.join(os.getcwd(), LIB_FOLDER))
    os.makedirs(target_dir, exist_ok=True)
    
    # Baixa binários Linux compatíveis
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", 
        "-r", "requirements.txt", 
        "-t", target_dir,
        "--platform", "manylinux2014_x86_64",
        "--only-binary=:all:",
        "--implementation", "cp",
        "--python-version", "3.11",
        "--abi", "cp311"
    ])
    print("✅ Bibliotecas baixadas!")

def create_zip():
    try:
        install_linux_deps()
    except Exception as e:
        print(f"⚠️ Erro no download Linux: {e}")

    print(f"📦 Criando {ZIP_NAME}...")
    if os.path.exists(ZIP_NAME): os.remove(ZIP_NAME)

    with zipfile.ZipFile(ZIP_NAME, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk('.'):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            for file in files:
                if file in IGNORE_FILES or file.endswith(('.log', '.pyc')): continue
                full_path = os.path.join(root, file)
                arcname = os.path.relpath(full_path, '.').replace(os.sep, '/')
                zf.write(full_path, arcname)
    
    print("✅ ZIP PRONTO!")

if __name__ == "__main__":
    create_zip()