import json
import os
import logging
from src.shared.llm import call_api_with_messages
from src.config import settings

def _load_prompt(filename):
    """
    Carrega o prompt procurando na pasta src/prompts relativo a este arquivo.
    """
    try:
        current_file_path = os.path.abspath(__file__)
        src_dir = os.path.dirname(os.path.dirname(current_file_path)) # Sobe para src/
        prompt_path = os.path.join(src_dir, "prompts", filename)
        prompt_path = os.path.normpath(prompt_path)

        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()
        else:
            # Fallback para raiz
            root_path = os.path.join(os.getcwd(), "prompts", filename)
            if os.path.exists(root_path):
                with open(root_path, "r", encoding="utf-8") as f:
                    return f.read()
            return None
    except Exception as e:
        logging.error(f"Erro ao ler prompt {filename}: {e}")
        return None

def classify_intent(query: str) -> dict:
    """
    Classifica a intenção do usuário usando o prompt classifier.md
    """
    # 1. Carrega o Prompt
    system_prompt = _load_prompt("classifier.md")
    
    if not system_prompt:
        logging.error("Prompt classifier.md não encontrado. Usando fallback.")
        return {"modulo": "fora_escopo", "sub_intencao": "erro_interno", "emocao": "neutro"}

    # 2. Injeta a pergunta
    final_prompt = system_prompt.replace("{pergunta}", query)

    # 3. Chama o LLM
    try:
        messages = [{"role": "user", "content": final_prompt}]
        
        # Deployment Fast para ser rápido
        deployment = getattr(settings, "AOAI_CHAT_DEPLOYMENT_FAST", None)
        
        resp, _, text = call_api_with_messages(
            messages, 
            max_tokens=200, 
            temperature=0.0,
            deployment_override=deployment
        )
        
        if not text:
            return {"modulo": "fora_escopo", "sub_intencao": "erro_llm"}

        # 4. Limpeza do JSON (Remove ```json ... ``` se houver)
        clean_text = text.strip()
        if clean_text.startswith("```"):
            clean_text = clean_text.split("```")[1]
            if clean_text.startswith("json"):
                clean_text = clean_text[4:]
        clean_text = clean_text.strip()
        clean_text = clean_text.strip("`") # Remove crases soltas

        # 5. Parse
        data = json.loads(clean_text)
        return data

    except json.JSONDecodeError:
        logging.warning(f"Erro ao decodificar JSON do classificador: {text}")
        # Fallback simples: se tiver "alocacao" no texto, assume alocacao
        if "alocacao" in text.lower():
            return {"modulo": "alocacao", "sub_intencao": "geral", "emocao": "neutro"}
        return {"modulo": "fora_escopo", "sub_intencao": "erro_parse", "emocao": "neutro"}
        
    except Exception as e:
        logging.exception(f"Erro crítico no classificador: {e}")
        return {"modulo": "fora_escopo", "sub_intencao": "erro_critico", "emocao": "neutro"}