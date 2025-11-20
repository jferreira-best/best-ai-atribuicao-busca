from src.orchestrator import classifier
from src.orchestrator.modules import avaliacao, classificacao, alocacao, fora_escopo

def route_request(query: str, full_body: dict):
    # 1. Classificação
    intent = classifier.classify_intent(query)
    modulo = intent.get("modulo", "").lower()
    
    # Adiciona dados brutos caso o módulo precise (ex: ID do usuário)
    context_data = {
        "intent": intent,
        "raw_body": full_body
    }

    print(f"Routing '{query}' -> Módulo: {modulo}")

    # 2. Despacho Dinâmico
    if modulo == "avaliacao":
        return avaliacao.run_chain(query, context_data)
    elif modulo == "classificacao":
        return classificacao.run_chain(query, context_data)
    elif modulo == "alocacao":
        return alocacao.run_chain(query, context_data)
    else:
        return fora_escopo.run_chain(query, context_data)