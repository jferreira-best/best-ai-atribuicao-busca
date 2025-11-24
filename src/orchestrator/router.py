import hashlib
from functools import lru_cache
from src.orchestrator import classifier
from src.orchestrator.modules import avaliacao, classificacao, alocacao, fora_escopo

# Cache em memória para as últimas 100 perguntas idênticas
@lru_cache(maxsize=100)
def _get_cached_response(query_hash):
    # Esta função serve apenas para o lru_cache funcionar.
    # O valor real é processado fora, mas podemos cachear o resultado final se estruturarmos bem.
    # Como o router chama funções complexas, vamos fazer um cache manual simples.
    pass

# Dicionário simples de cache (Global no contexto da Function acordada)
RESPONSE_CACHE = {}

def route_request(query: str, full_body: dict):
    # 1. Verifica Cache
    # Cria um hash da pergunta para servir de chave
    query_key = hashlib.md5(query.strip().lower().encode('utf-8')).hexdigest()
    
    if query_key in RESPONSE_CACHE:
        print(f"⚡ Cache Hit! Retornando resposta instantânea para: '{query}'")
        return RESPONSE_CACHE[query_key]

    # 2. Fluxo Normal
    intent = classifier.classify_intent(query)
    modulo = intent.get("modulo", "").lower()
    
    context_data = {
        "intent": intent,
        "raw_body": full_body
    }

    print(f"Routing '{query}' -> Módulo: {modulo}")

    if modulo == "avaliacao":
        result = avaliacao.run_chain(query, context_data)
    elif modulo == "classificacao":
        result = classificacao.run_chain(query, context_data)
    elif modulo == "alocacao":
        result = alocacao.run_chain(query, context_data)
    else:
        result = fora_escopo.run_chain(query, context_data)

    # 3. Salva no Cache antes de retornar
    RESPONSE_CACHE[query_key] = result
    
    return result