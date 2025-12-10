import os
import logging
from datetime import datetime
from azure.data.tables import TableClient
from azure.core.exceptions import ResourceExistsError, HttpResponseError

# --- CONFIGURAÇÃO ---
# Se estiver rodando local, ele pega do local.settings.json
# Em produção, ele pega das Variáveis de Ambiente da Function App
CONN_STR = os.environ.get("AzureWebJobsStorage") 

# MUDANÇA AQUI: Nome exclusivo para este projeto
TABLE_NAME = "ChatEstadoAtribuicao" #dev 
#TABLE_NAME = "ChatEstadoAtribuicaoprod" #prod
def _get_table_client():
    if not CONN_STR:
        logging.error("String de conexão 'AzureWebJobsStorage' não encontrada.")
        return None

    try:
        client = TableClient.from_connection_string(conn_str=CONN_STR, table_name=TABLE_NAME)
        # Tenta criar a tabela se não existir (operação rápida e segura)
        try:
            client.create_table()
        except ResourceExistsError:
            pass # Tabela já existe, tudo bem
        return client
    except Exception as e:
        logging.error(f"Erro ao conectar no Table Storage: {e}")
        return None

def get_history(session_id: str, limit: int = 10):
    """
    Recupera as últimas mensagens de uma sessão.
    Retorna lista no formato: [{'role': 'user', 'content': '...'}, ...]
    """
    if not session_id:
        return []

    client = _get_table_client()
    if not client:
        return []

    try:
        # Filtra pela PartitionKey (SessionID)
        filter_query = f"PartitionKey eq '{session_id}'"
        
        # Pega as entidades
        entities = list(client.query_entities(filter_query))
        
        # Ordena pelo RowKey (Timestamp) para garantir ordem cronológica
        entities.sort(key=lambda x: x['RowKey'])
        
        # Formata para o padrão OpenAI/LLM
        history = []
        for ent in entities:
            history.append({
                "role": ent.get("Role", "user"),
                "content": ent.get("Content", "")
            })
            
        # Retorna apenas as últimas N interações para não estourar o contexto do LLM
        return history[-limit:] 
        
    except Exception as e:
        logging.error(f"Erro ao ler histórico da tabela {TABLE_NAME}: {e}")
        return []

def add_interaction(session_id: str, user_msg: str, bot_response: str):
    """
    Salva a pergunta do usuário e a resposta do bot na tabela.
    """
    if not session_id:
        return

    client = _get_table_client()
    if not client:
        return

    try:
        # Gera RowKeys baseados no tempo reverso ou sequencial
        # Usamos formato YYYYMMDDHHMMSSffffff para ordenação simples de string
        timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S%f')
        
        # 1. Salva Mensagem do Usuário
        user_entity = {
            "PartitionKey": session_id,
            "RowKey": f"{timestamp}_1_user", # Sufixo garante ordem
            "Role": "user",
            "Content": user_msg
        }
        client.create_entity(entity=user_entity)

        # 2. Salva Resposta do Bot
        bot_entity = {
            "PartitionKey": session_id,
            "RowKey": f"{timestamp}_2_assistant",
            "Role": "assistant",
            "Content": bot_response
        }
        client.create_entity(entity=bot_entity)
        
    except Exception as e:
        logging.error(f"Erro ao salvar interação na tabela {TABLE_NAME}: {e}")