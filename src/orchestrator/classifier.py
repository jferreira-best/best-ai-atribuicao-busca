import json
import os
from src.shared.llm import call_api_with_messages
from src.config import settings # Importe settings


def classify_intent(question: str):
    # Caminho absoluto para garantir leitura no Azure Functions
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompt_path = os.path.join(base_dir, "prompts", "classifier.md")
    
    with open(prompt_path, "r", encoding="utf-8") as f:
        template = f.read()
        
    final_prompt = template.replace("{pergunta}", question)
    
    messages = [
        {"role": "system", "content": "Você é um classificador JSON estrito."},
        {"role": "user", "content": final_prompt}
    ]
    
    resp, _, content = call_api_with_messages(
        messages, 
        max_tokens=150, 
        temperature=0.0,
        deployment_override=settings.AOAI_CHAT_DEPLOYMENT_FAST 
    )

    # Usa token baixo para ser rápido
    #resp, _, content = call_api_with_messages(messages, max_tokens=150, temperature=0.0)
    
    try:
        # Limpeza básica de markdown json
        cleaned = content.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)
    except:
        # Fallback seguro
        return {"modulo": "fora_escopo", "sub_intencao": "geral", "emocao": "neutro"}