import hashlib
from functools import lru_cache
from src.orchestrator import classifier
from src.orchestrator.modules import avaliacao, classificacao, alocacao, fora_escopo

# Cache em memória
RESPONSE_CACHE = {}

def route_request(query: str, full_body: dict):
    # 1. Verifica Cache
    query_key = hashlib.md5(query.strip().lower().encode('utf-8')).hexdigest()
    if query_key in RESPONSE_CACHE:
        print(f"⚡ Cache Hit! Retornando resposta instantânea para: '{query}'")
        return RESPONSE_CACHE[query_key]

    # =========================================================================
    # 2. FAST TRACK (VIA RÁPIDA) - SUPORTE & INSISTÊNCIA
    # Se o usuário pedir ajuda/chamado, pulamos a classificação do LLM
    # e forçamos a ida para o módulo de avaliação (onde está a regra do Trio Gestor).
    # =========================================================================
    termos_suporte = ["chamado", "abrir chamado", "suporte", "ajuda", "não entendi", "nao entendi", "reclamar", "discordo"]
    query_lower = query.lower()

    if any(t in query_lower for t in termos_suporte):
        print(f"🚨 Fast Track acionado: '{query}' -> Forçando Módulo: avaliacao")
        intent = {
            "modulo": "avaliacao",
            "sub_intencao": "suporte_insistencia",
            "emocao": "neutro" # ou "frustrado" se quiser forçar
        }
    else:
        # 3. Fluxo Normal (Pergunta ao Classificador LLM)
        intent = classifier.classify_intent(query)
    # =========================================================================

    modulo = intent.get("modulo", "").lower()
    
    context_data = {
        "intent": intent,
        "raw_body": full_body
    }

    print(f"Routing '{query}' -> Módulo: {modulo}")

    if modulo == "avaliacao":
        # Aqui ele vai entrar no seu script avaliacao.py, 
        # cair no 'if not docs and eh_suporte', 
        # pegar o prompt .md e devolver o link do chamado.
        result = avaliacao.run_chain(query, context_data)
        
    elif modulo == "classificacao":
        result = classificacao.run_chain(query, context_data)
    elif modulo == "alocacao":
        result = alocacao.run_chain(query, context_data)
    else:
        result = fora_escopo.run_chain(query, context_data)

    # 4. Salva no Cache
    RESPONSE_CACHE[query_key] = result
    
    return result