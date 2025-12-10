import os
import logging
import requests
from typing import List, Dict, Any, Tuple, Optional
from src.config import settings # Importe as settings

# Configuração de Logging
logger = logging.getLogger(__name__)

# --- Helpers de Configuração (Extraídos do function_app.py) ---
def _safe_str_env(key: str, default: str) -> str:
    val = os.environ.get(key)
    if val is None:
        return default
    return val

def _safe_int_env(key: str, default: int) -> int:
    val = os.environ.get(key)
    if val is None or val == "":
        return default
    try:
        return int(val)
    except ValueError:
        logger.error(f"Env var {key} tem valor inválido. Usando default {default}.")
        return default

# --- Carregamento de Variáveis de Ambiente (Contexto LLM) ---
# Azure OpenAI (AOAI)
AOAI_ENDPOINT = _safe_str_env("AOAI_ENDPOINT", "").rstrip("/")
AOAI_API_KEY = _safe_str_env("AOAI_API_KEY", "")
AOAI_CHAT_DEPLOYMENT = _safe_str_env("AOAI_CHAT_DEPLOYMENT", "")
AOAI_API_VERSION = _safe_str_env("AOAI_API_VERSION", "2023-10-01")

# OpenAI Pública (Fallback)
OPENAI_API_KEY = _safe_str_env("OPENAI_API_KEY", "")
OPENAI_MODEL = _safe_str_env("OPENAI_MODEL", "gpt-4o-mini")

# Timeouts
HTTP_TIMEOUT_LONG = _safe_int_env("HTTP_TIMEOUT_LONG", 20)


def call_api_with_messages(
    messages_to_send: List[Dict[str, str]], 
    max_tokens: int = 400, 
    temperature: float = 0.0,
    deployment_override: str = None
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[str]]:
    """
    Função centralizada para chamar LLM (Azure OpenAI ou OpenAI Pública).
    
    Retorna uma tupla: (full_response_json, finish_reason, content_text)
    """
    # Decide qual deployment usar
    deployment = deployment_override or settings.AOAI_CHAT_DEPLOYMENT

    try:
        # 1. Tentativa: Azure OpenAI (Prioritário)
        if settings.AOAI_ENDPOINT and settings.AOAI_API_KEY and deployment:
            # Usa a variável 'deployment' na URL
            url = f"{settings.AOAI_ENDPOINT}/openai/deployments/{deployment}/chat/completions?api-version={settings.AOAI_API_VERSION}"
        #if AOAI_ENDPOINT and AOAI_API_KEY and AOAI_CHAT_DEPLOYMENT:
        #    url = f"{AOAI_ENDPOINT}/openai/deployments/{AOAI_CHAT_DEPLOYMENT}/chat/completions?api-version={AOAI_API_VERSION}"
            headers = {
                "api-key": AOAI_API_KEY, 
                "Content-Type": "application/json"
            }
            payload = {
                "messages": messages_to_send, 
                "max_tokens": max_tokens, 
                "temperature": temperature
            }
            
            r = requests.post(url, headers=headers, json=payload, timeout=HTTP_TIMEOUT_LONG)
            r.raise_for_status()
            
            resp = r.json()
            
            # Extração segura do conteúdo
            try:
                txt = resp["choices"][0]["message"].get("content")
            except Exception:
                # Fallback para formatos antigos ou completions não-chat
                txt = resp.get("choices", [{}])[0].get("text")
            
            fr = resp["choices"][0].get("finish_reason") if resp.get("choices") else None
            
            return resp, fr, txt

        # 2. Tentativa: Public OpenAI (Fallback)
        if OPENAI_API_KEY:
            url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENAI_API_KEY}", 
                "Content-Type": "application/json"
            }
            payload = {
                "model": OPENAI_MODEL, 
                "messages": messages_to_send, 
                "max_tokens": max_tokens, 
                "temperature": temperature
            }
            
            r = requests.post(url, headers=headers, json=payload, timeout=HTTP_TIMEOUT_LONG)
            r.raise_for_status()
            
            resp = r.json()
            txt = resp["choices"][0]["message"].get("content")
            fr = resp["choices"][0].get("finish_reason")
            
            return resp, fr, txt
            
    except Exception as e:
        logger.exception("Erro ao chamar LLM (shared/llm.py): %s", e)

    # Retorno padrão em caso de falha total
    return None, None, None