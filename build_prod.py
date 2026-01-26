import zipfile
import os
import sys

# Nome do arquivo de saída
ZIP_NAME = "deploy.zip"

# O que NÃO deve ir para o zip (Lixo e ambientes virtuais)
IGNORE_DIRS = {'.git', '.vscode', '.venv', 'env', '__pycache__', '.idea'}
IGNORE_FILES = {ZIP_NAME, 'build.py', 'deploy_prod.ps1', 'deploy_prod_emergency.ps1'}

def create_zip():
    print(f"📦 Criando {ZIP_NAME} formatado para Linux...")
    
    if os.path.exists(ZIP_NAME):
        os.remove(ZIP_NAME)

    count = 0
    with zipfile.ZipFile(ZIP_NAME, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk('.'):
            # Remove pastas ignoradas da lista para não entrar nelas
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
            
            for file in files:
                if file in IGNORE_FILES or file.endswith('.log'):
                    continue
                
                full_path = os.path.join(root, file)
                # O PULO DO GATO: Força a barra ser '/' para o Linux entender que é pasta
                arcname = os.path.relpath(full_path, '.').replace(os.sep, '/')
                
                zf.write(full_path, arcname)
                count += 1

    print(f"✅ Sucesso! {count} arquivos compactados corretamente.")

if __name__ == "__main__":
    create_zip()