import json
import os
import logging
import re

from src.shared.llm import call_api_with_messages
from src.config import settings


def _load_prompt(filename: str) -> str | None:
    """
    Carrega o prompt procurando na pasta src/prompts relativo a este arquivo.
    """
    try:
        current_file_path = os.path.abspath(__file__)
        # Sobe para src/
        src_dir = os.path.dirname(os.path.dirname(current_file_path))
        prompt_path = os.path.join(src_dir, "prompts", filename)
        prompt_path = os.path.normpath(prompt_path)

        if os.path.exists(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                return f.read()

        # Fallback para raiz do projeto
        root_path = os.path.join(os.getcwd(), "prompts", filename)
        if os.path.exists(root_path):
            with open(root_path, "r", encoding="utf-8") as f:
                return f.read()

        logging.error(f"Prompt {filename} não encontrado em src/prompts nem em ./prompts.")
        return None

    except Exception as e:
        logging.error(f"Erro ao ler prompt {filename}: {e}")
        return None


def _extract_json_block(text: str) -> str | None:
    """
    Tenta extrair um bloco JSON válido da resposta do modelo.

    - Remove ```json ... ``` se existir;
    - Tenta usar o texto inteiro;
    - Como fallback, procura o primeiro bloco {...} com regex.
    """
    if not text:
        return None

    clean = text.strip()

    # Remove blocos ```...``` se houver
    if clean.startswith("```"):
        parts = clean.split("```")
        # partes ímpares costumam ser o conteúdo
        if len(parts) >= 2:
            clean = parts[1].strip()
        # Remove prefixo "json"
        if clean.lower().startswith("json"):
            clean = clean[4:].strip()

    # Remove crases soltas
    clean = clean.strip("`").strip()

    # 1) tenta interpretar o texto todo
    try:
        json.loads(clean)
        return clean
    except Exception:
        pass

    # 2) tenta achar o primeiro {...} na resposta
    match = re.search(r"\{.*\}", clean, re.DOTALL)
    if match:
        candidate = match.group(0)
        try:
            json.loads(candidate)
            return candidate
        except Exception:
            pass

    return None


def classify_intent(query: str) -> dict:
    """
    Classifica a intenção do usuário usando o prompt classifier.md.

    Espera que o modelo devolva um JSON com, por exemplo:
    {
      "modulo": "avaliacao",
      "sub_intencao": "entender_resultado",
      "emocao": "duvida",
      "confianca": 0.95
    }
    """
    # 1. Carrega o Prompt
    system_prompt = _load_prompt("classifier.md")

    if not system_prompt:
        logging.error("Prompt classifier.md não encontrado. Usando fallback.")
        return {
            "modulo": "fora_escopo",
            "sub_intencao": "erro_interno",
            "emocao": "neutro",
        }

    # 2. Monta mensagens: prompt como system, pergunta como user
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    # 3. Escolhe deployment (FAST se existir, senão o padrão)
    deployment = getattr(
        settings,
        "AOAI_CHAT_DEPLOYMENT_FAST",
        getattr(settings, "AOAI_CHAT_DEPLOYMENT", None),
    )

    try:
        resp, _, text = call_api_with_messages(
            messages,
            max_tokens=200,
            temperature=0.0,
            deployment_override=deployment,
        )

        if not text:
            logging.warning("Classificador retornou texto vazio.")
            return {
                "modulo": "fora_escopo",
                "sub_intencao": "erro_llm",
                "emocao": "neutro",
            }

        logging.debug(f"Resposta bruta do classificador: {text}")

        # 4. Extrai bloco JSON da resposta
        json_block = _extract_json_block(text)
        if not json_block:
            logging.warning(f"Não foi possível extrair JSON da resposta: {text}")
            return {
                "modulo": "fora_escopo",
                "sub_intencao": "erro_parse",
                "emocao": "neutro",
            }

        # 5. Parse definitivo
        data = json.loads(json_block)

        # Garantia mínima de chaves obrigatórias
        if "modulo" not in data:
            data["modulo"] = "fora_escopo"
        if "sub_intencao" not in data:
            data["sub_intencao"] = "geral"
        if "emocao" not in data:
            data["emocao"] = "neutro"

        return data

    except json.JSONDecodeError:
        logging.exception("Erro ao decodificar JSON do classificador.")
        return {
            "modulo": "fora_escopo",
            "sub_intencao": "erro_parse",
            "emocao": "neutro",
        }

    except Exception as e:
        logging.exception(f"Erro crítico no classificador: {e}")
        return {
            "modulo": "fora_escopo",
            "sub_intencao": "erro_critico",
            "emocao": "neutro",
        }
