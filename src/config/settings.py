import os

def _safe_str(key, default=""):
    return os.environ.get(key, default)

def _safe_int(key, default=0):
    try:
        return int(os.environ.get(key, default))
    except:
        return default

# --- Azure Search ---
SEARCH_ENDPOINT = _safe_str("COG_SEARCH_ENDPOINT") or _safe_str("SEARCH_ENDPOINT")
SEARCH_KEY = _safe_str("COG_SEARCH_KEY") or _safe_str("SEARCH_API_KEY")
SEARCH_INDEX = _safe_str("COG_SEARCH_INDEX") or _safe_str("SEARCH_INDEX")
SEARCH_API_VERSION = _safe_str("COG_SEARCH_API_VERSION", "2023-11-01")
ENABLE_SEMANTIC = _safe_str("ENABLE_SEMANTIC", "true").lower() == "true"
SEMANTIC_CONFIG = _safe_str("COG_SEARCH_SEM_CONFIG", "default")

# --- OpenAI / Azure OpenAI ---
AOAI_ENDPOINT = _safe_str("AOAI_ENDPOINT").rstrip("/")
AOAI_API_KEY = _safe_str("AOAI_API_KEY")
AOAI_EMB_DEPLOYMENT = _safe_str("AOAI_EMB_DEPLOYMENT") # Para Embeddings
AOAI_CHAT_DEPLOYMENT = _safe_str("AOAI_CHAT_DEPLOYMENT") # Para Chat
AOAI_CHAT_DEPLOYMENT_FAST= _safe_str("AOAI_CHAT_DEPLOYMENT_FAST", "gpt-4o-mini")
AOAI_API_VERSION = _safe_str("AOAI_API_VERSION", "2023-05-15")

# --- Geral ---
EMBED_DIM = _safe_int("EMBED_DIM", 3072) # text-embedding-3-large geralmente
HTTP_TIMEOUT_SHORT = _safe_int("HTTP_TIMEOUT_SHORT", 8)
HTTP_TIMEOUT_LONG = _safe_int("HTTP_TIMEOUT_LONG", 30)
DEFAULT_TOPK = _safe_int("DEFAULT_TOPK", 3) #reduzi era 5, de 4 para 3

# --- Mensagens de Sistema / Respostas Padrão ---
MSG_ENCERRAMENTO_FORCADO = (
    "Respeitamos a sua manifestação! Entretanto, no campo de um agente digital "
    "as orientações foram esgotadas. A partir deste momento o suporte humano "
    "é o indicado para seguir com o diálogo."
)