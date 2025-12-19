import os
from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv

# Carrega suas configurações
load_dotenv()
ENDPOINT = os.environ.get("COG_SEARCH_ENDPOINT")
KEY = os.environ.get("COG_SEARCH_KEY")
INDEX_NAME = os.environ.get("COG_SEARCH_INDEX", "kb-atribuicao")

def verificar_indice():
    if not ENDPOINT or not KEY:
        print("Erro: Configure as variáveis de ambiente COG_SEARCH_ENDPOINT e COG_SEARCH_KEY.")
        return

    client = SearchIndexClient(endpoint=ENDPOINT, credential=AzureKeyCredential(KEY))
    
    try:
        print(f"🔍 Inspecionando índice: {INDEX_NAME}...")
        index = client.get_index(INDEX_NAME)
        
        vector_field = next((f for f in index.fields if f.name == "content_vector"), None)
        
        if vector_field:
            dims = vector_field.vector_search_dimensions
            print(f"📊 Dimensões atuais do 'content_vector': {dims}")
            
            if dims == 3072:
                print("✅ STATUS: CORRETO! O índice suporta text-embedding-3-large.")
            elif dims == 1536:
                print("❌ STATUS: ERRADO! O índice está configurado para ada-002 (pequeno).")
                print("   AÇÃO: Você precisa apagar e recriar o índice.")
            else:
                print(f"⚠️ STATUS: ESTRANHO. Dimensão {dims} não é padrão.")
        else:
            print("❌ Campo 'content_vector' não encontrado!")
            
    except Exception as e:
        print(f"❌ Erro ao ler índice (ele existe?): {e}")

if __name__ == "__main__":
    verificar_indice()