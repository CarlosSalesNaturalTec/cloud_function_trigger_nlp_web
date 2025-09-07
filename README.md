# Módulo: `cloud_function_trigger_nlp_web`

## 1. Visão Geral

Esta Cloud Function representa o segundo estágio da pipeline de processamento de dados da web. Sua responsabilidade é detectar quando o serviço `scraper_newspaper3k` concluiu seu trabalho (indicado pela mudança de status de um documento para `scraper_ok` na coleção `monitor_results`) e, em seguida, acionar o serviço `api_nlp` para realizar a análise de Processamento de Linguagem Natural no texto extraído.

A função utiliza um gatilho condicional para garantir que seja executada apenas na transição de status relevante, evitando invocações desnecessárias.

---


## 2. Detalhes Técnicos / Pilha Tecnológica

-   **Ambiente de Execução:** Google Cloud Functions (1ª geração)
-   **Runtime:** Python 3.12+
-   **Framework:** [Google Cloud Functions Framework](https://github.com/GoogleCloudPlatform/functions-framework-python)
-   **Dependências Principais:**
    -   `functions-framework`: Para o boilerplate e execução da função.
    -   `requests`: Para realizar chamadas HTTP para o serviço `api_nlp`.
    -   `google-auth` e `google-oauth2`: Para gerar um ID Token e autenticar a chamada para o serviço `api_nlp`.
    -   `firebase-admin`: Para se conectar ao Firestore e escrever na coleção `system_logs`.

---


## 3. Gatilho (Trigger)

-   **Tipo:** Firestore Trigger (Nativo de 1ª Geração)
-   **Evento:** `providers/cloud.firestore/eventTypes/document.update`
-   **Recurso:** `projects/{project_id}/databases/(default)/documents/monitor_results/{doc_id}`
-   **Condição (Filtro de Evento):** A lógica interna da função verifica se o campo `status` no payload do evento mudou de qualquer valor para `scraper_ok`. Isso garante que o NLP seja acionado apenas uma vez, no momento exato em que o scraping é concluído com sucesso.

---


## 4. Variáveis de Ambiente

| Variável                | Descrição                                                                                                | Exemplo                                                          |
| ----------------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `API_NLP_SERVICE_URL`   | A URL completa do serviço `api_nlp` implantado no Google Cloud Run. Será usada como *audience* para o ID Token e como alvo da chamada HTTP. | `https://api-nlp-abcdef-uc.a.run.app` |

---


## 5. Lógica de Execução

1.  A função é ativada por um evento de atualização de documento no Firestore.
2.  Ela inspeciona os dados do evento (`value` e `oldValue`) para extrair o status do documento antes e depois da mudança.
3.  **Filtro Condicional:** A função prossegue apenas se `status_depois == 'scraper_ok'` e `status_antes != 'scraper_ok'`. Caso contrário, a execução é encerrada com um log informativo.
4.  Se a condição for atendida, um novo documento é criado na coleção `system_logs` com o status `processing`.
5.  Um ID Token JWT é gerado com a `API_NLP_SERVICE_URL` como audiência.
6.  A função monta a URL do endpoint alvo: `{API_NLP_SERVICE_URL}/process/web/{doc_id}`.
7.  Uma requisição `POST` é enviada para a URL alvo com o token de autenticação.
8.  O documento de log em `system_logs` é atualizado para `success` ou `failed`, dependendo do resultado da chamada, e a exceção é propagada em caso de falha para acionar retentativas.

---


## 6. Modelo de Dados (`system_logs`)

A função cria e atualiza um documento na coleção `system_logs` com a seguinte estrutura:

```json
{
  "run_id": "string (uuid4)",
  "module": "trigger-nlp-web",
  "target_doc_id": "string",
  "start_time": "timestamp",
  "end_time": "timestamp",
  "status": "string ('processing', 'success', 'failed')",
  "details": "string",
  "error_details": "string (opcional)"
}
```

---


## 7. Permissões de IAM

A conta de serviço associada a esta Cloud Function precisa ter as seguintes permissões:

-   **Role 1:** `Cloud Run Invoker` (`roles/run.invoker`)
    -   **No Recurso:** No serviço `api-nlp` do Cloud Run.
-   **Role 2:** `Cloud Datastore User` (`roles/datastore.user`)
    -   **No Recurso:** No projeto GCP (para permitir escrita no Firestore).

---


## 8. Relação com Outros Módulos

-   **Origem do Evento:** A função é acionada por uma atualização de status (`scraper_ok`) feita pelo serviço `scraper_newspaper3k` na coleção `monitor_results`.
-   **Destino da Ação:** A função invoca o endpoint `POST /process/web/{doc_id}` no serviço `api_nlp`.
-   **Próximo Passo na Pipeline:** Este é o último passo da pipeline de processamento web. Após a execução do `api_nlp`, o documento em `monitor_results` conterá os dados de sentimento e entidades.

---


## 9. Notas de Implementação e Histórico

Seguindo o padrão estabelecido pelo `trigger-scraper`, esta função foi migrada de 2ª para 1ª Geração para garantir a estabilidade do gatilho do Firestore, contornando problemas com a infraestrutura do Eventarc. O método de autenticação também foi refatorado para usar `google.oauth2.id_token.fetch_id_token`, que é a abordagem correta para o ambiente de Cloud Functions.

---


## 10. Exemplo de Comando de Deploy (1ª Geração)

Execute o comando a partir da raiz do projeto. Lembre-se de substituir `"URL_DO_SEU_SERVICO_NLP"` pela URL real do seu serviço no Cloud Run.

```bash
gcloud functions deploy trigger-nlp-web-v1 \
  --no-gen2 \
  --runtime=python312 \
  --trigger-event="providers/cloud.firestore/eventTypes/document.update" \
  --trigger-resource="projects/monitora-parlamentar-elmar/databases/(default)/documents/monitor_results/{docId}" \
  --source=cloud_function_trigger_nlp_web \
  --entry-point=trigger_nlp_web \
  --region=us-central1 \
  --set-env-vars API_NLP_SERVICE_URL="URL_DO_SEU_SERVICO_NLP"
```
