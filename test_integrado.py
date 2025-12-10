import os
# Carrega variáveis de ambiente locais se necessário
# from dotenv import load_dotenv
# load_dotenv()

from src.orchestrator import router

# Perguntas de teste baseadas nos seus exemplos
test_questions = [
    "Minha nota do farol está errada, eu tive 96% de presença!",
    "Como funciona o cálculo da classificação?",
    "Fui alocado na escola errada, quero mudar.",
    "O que tem para o almoço hoje?"
]

if __name__ == "__main__":
    print("=== INICIANDO TESTE DO ORQUESTRADOR ===\n")
    
    for q in test_questions:
        result = router.route_request(q)
        print(f"🤖 Resposta Bot: {result['resposta_texto']}")
        print("-" * 50 + "\n")