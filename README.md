# 🤖 Assistente Virtual de Atribuição de Aulas - SEDUC-SP

Este projeto consiste em um **Assistente Virtual Inteligente (Chatbot)** desenvolvido para auxiliar docentes e gestores da Secretaria da Educação do Estado de São Paulo (SEDUC-SP) com dúvidas sobre **Atribuição de Aulas**, **Avaliação de Desempenho** e **Classificação**.

O sistema utiliza uma arquitetura **RAG (Retrieval-Augmented Generation)** Híbrida para garantir respostas técnicas precisas, baseadas estritamente nas normas e resoluções vigentes, minimizando alucinações.

---

## 🚀 Funcionalidades Principais

* **RAG Híbrido (Vetorial + Semântico):** Combina busca por similaridade (Embeddings) com busca semântica (Keywords + Rerank) para encontrar trechos exatos em PDFs complexos.
* **Orquestrador Inteligente (`router.py`):**
    * Classifica a intenção do usuário (Técnica vs. Administrativa vs. Fora de Escopo).
    * Identifica sentimentos (Raiva/Frustração) para atendimento empático.
    * Gerencia fluxo de escalonamento (Sugere escola -> Diretoria -> Chamado).
* **Contexto Conversacional:** Mantém memória de curto prazo para entender referências como "e para contratado?" ou "não concordo".
* **Engenharia de Prompt Estrutural:** Prompts dinâmicos que adaptam o tom de voz (Empático, Técnico, Diretivo) sem aumentar a temperatura do modelo.
* **Circuit Breaker:** Bloqueia interações repetitivas ou encerradas para economia de tokens.
* **Filtros de Escopo:** Bloqueia ativamente dúvidas de alunos/pais (ex: boletim, notas) focando exclusivamente no público docente.

---

## 🛠️ Stack Tecnológica

* **Linguagem:** Python 3.10+
* **Cloud:** Azure Functions (Serverless)
* **LLM:** Azure OpenAI (GPT-4 / GPT-3.5-Turbo)
* **Embeddings:** Azure OpenAI (`text-embedding-3-large` ou similar)
* **Busca:** Azure AI Search (Vector Search + Semantic Ranker)
* **Armazenamento de Estado:** Azure Table Storage (Histórico de sessões)

---

## 📂 Estrutura do Projeto

```text
src/
├── config/
│   └── settings.py       # Variáveis de ambiente e configurações globais
├── orchestrator/
│   ├── classifier.py     # Classificador de intenções (LLM)
│   └── router.py         # Cérebro do sistema (Decide o fluxo da conversa)
├── prompts/
│   ├── classifier.md     # Regras de classificação e detecção de emoção
│   ├── alocacao.md       # Prompt especialista em Atribuição/PEI
│   ├── avaliacao.md      # Prompt especialista em Avaliação de Desempenho
│   ├── classificacao.md  # Prompt especialista em Pontuação/Vunesp
│   └── templates/        # Respostas estáticas (Escola, Regional, Chamado)
├── search/
│   └── rag_core.py       # Lógica de busca híbrida (Vector + Text + Rerank)
├── shared/
│   ├── llm.py            # Wrapper para chamadas à API da OpenAI
│   ├── state_manager.py  # Gestão de histórico no Table Storage
│   └── utils.py          # Funções auxiliares (limpeza de texto, etc.)
└── function_app.py       # Entry point da Azure Function

#rodar direto :func azure functionapp publish see-d-crm-ingestaobot --build remote
#az login --use-device-code