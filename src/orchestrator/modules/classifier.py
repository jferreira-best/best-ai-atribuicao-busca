# src/orchestrator/classifier.py
from typing import Dict, Any
from src.search.rag_core import _call_api_with_messages  # ou um wrapper mais genérico

CLASSIFIER_SYSTEM = """
Você é um classificador de intenções. Analise a pergunta do docente e identifique:

MÓDULO (qual tema):

avaliacao (farol, nota, desempenho)
classificacao (ranking, posição, pontos)
alocacao (escola, turma, atribuição)
fora_escopo (outros assuntos)

SUB-INTENÇÃO (o que ele quer):

entender_resultado (por que recebi X?)
questionar_calculo (meus dados não batem)
comparar (por que fulano/antes era diferente?)
como_melhorar (o que fazer para mudar?)
processo (como funciona?)

SINAIS DE FRUSTRAÇÃO:

neutro / frustrado / revoltado

Analise SEMANTICAMENTE, não por keywords.

Retorne JSON: { "modulo": "...", "sub_intencao": "...", "emocao": "...",
"confianca": 0.0-1.0, "palavras_chave": [...] }
"""

def classify_question(pergunta: str) -> Dict[str, Any]:
    messages = [
        {"role": "system", "content": CLASSIFIER_SYSTEM},
        {"role": "user", "content": f"PERGUNTA DO DOCENTE: {pergunta}"}
    ]
    resp, _, txt = _call_api_with_messages(messages, max_tokens=300)
    # parse JSON aqui (try/except e defaults)
    ...
