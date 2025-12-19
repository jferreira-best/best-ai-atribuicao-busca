import os
import logging

# Configuração de Logs
logging.basicConfig(level=logging.INFO)

def _safe_str(key, default=""):
    val = os.environ.get(key, default)
    # Se quiser debugar variáveis vazias, descomente a linha abaixo:
    # if not val: logging.warning(f"[CONFIG] Variável '{key}' não encontrada.")
    return val

def _safe_int(key, default=0):
    try:
        return int(os.environ.get(key, default))
    except:
        return default

# --- AZURE AI SEARCH (RAG) ---
# Mapeia as chaves do local.settings.json (COG_*) para as variáveis do Python
SEARCH_ENDPOINT = _safe_str("COG_SEARCH_ENDPOINT", "")
SEARCH_KEY = _safe_str("COG_SEARCH_KEY", "")
SEARCH_INDEX = _safe_str("COG_SEARCH_INDEX", "kb-atribuicao")
# AQUI ESTAVA O ERRO: Esta variável é obrigatória agora
SEARCH_SEMANTIC_CONFIG = _safe_str("COG_SEARCH_SEM_CONFIG", "kb-atribuicao-semantic")
SEARCH_API_VERSION = _safe_str("COG_SEARCH_API_VERSION", "2024-07-01")

# --- AZURE OPENAI (LLM) ---
AOAI_ENDPOINT = _safe_str("AOAI_ENDPOINT", "")
AOAI_API_KEY = _safe_str("AOAI_API_KEY", "")
AOAI_API_VERSION = _safe_str("AOAI_API_VERSION", "2024-08-01-preview")
AOAI_CHAT_DEPLOYMENT = _safe_str("AOAI_CHAT_DEPLOYMENT", "gpt-4o-mini")
AOAI_EMB_DEPLOYMENT = _safe_str("AOAI_EMB_DEPLOYMENT", "text-embedding-3-large")

# --- TABLE STORAGE ---
AzureWebJobsStorage = _safe_str("AzureWebJobsStorage", "")
TABLE_NAME = _safe_str("TABLE_NAME", "ChatEstadoAtribuicao")

# --- OPENAI PÚBLICA (Fallback) ---
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "") 
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4-turbo")

# --- TIMEOUTS & MENSAGENS ---
HTTP_TIMEOUT_SHORT = _safe_int("HTTP_TIMEOUT_SHORT", 5)
HTTP_TIMEOUT_LONG = _safe_int("HTTP_TIMEOUT_LONG", 30)
MSG_ENCERRAMENTO_FORCADO = "Este atendimento foi encerrado. Por favor, inicie uma nova conversa."