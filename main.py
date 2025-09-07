import os
import logging
import uuid
from datetime import datetime, timezone

import functions_framework
import google.auth
import google.auth.transport.requests
import requests
from google.oauth2 import id_token
from cloudevents.http import CloudEvent
import firebase_admin
from firebase_admin import firestore

# --- Configuração de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Inicialização do Firebase ---
try:
    firebase_admin.initialize_app()
    db = firestore.client()
    logging.info("Conexão com o Firestore estabelecida com sucesso.")
except Exception as e:
    logging.error(f"Erro ao inicializar o Firebase Admin: {e}")
    db = None

# --- Carregamento de Variáveis de Ambiente ---
API_NLP_SERVICE_URL = os.environ.get("API_NLP_SERVICE_URL")
if not API_NLP_SERVICE_URL:
    logging.error("A variável de ambiente API_NLP_SERVICE_URL não foi definida.")
    raise ValueError("API_NLP_SERVICE_URL must be set.")

def get_auth_token():
    """Obtém um token de identidade do Google para invocar serviços do Cloud Run."""
    try:
        auth_req = google.auth.transport.requests.Request()
        token = id_token.fetch_id_token(auth_req, API_NLP_SERVICE_URL)
        return token
    except Exception as e:
        logging.error(f"Erro ao gerar o token de autenticação: {e}")
        raise

@functions_framework.cloud_event
def trigger_nlp_web(cloud_event: CloudEvent):
    """
    Cloud Function acionada pela atualização de um documento no Firestore
    na coleção 'monitor_results', especificamente quando o status muda para 'scraper_ok'.
    """
    if not db:
        logging.critical("Cliente Firestore não está disponível. A função não pode continuar.")
        return

    resource_string = cloud_event["subject"]
    doc_id = resource_string.split('/')[-1]

    # --- Lógica de Filtro de Evento ---
    try:
        data = cloud_event.data["value"]["fields"]
        before_data = cloud_event.data["oldValue"]["fields"]
        
        status_after = data.get("status", {}).get("stringValue")
        status_before = before_data.get("status", {}).get("stringValue")

        if not (status_after == 'scraper_ok' and status_before != 'scraper_ok'):
            logging.info(f"Evento para doc_id {doc_id} ignorado. Mudança de status não relevante (de '{status_before}' para '{status_after}').")
            return
    except KeyError as e:
        logging.warning(f"Não foi possível encontrar os campos de status no evento para o doc_id {doc_id}. Chave ausente: {e}. Ignorando evento.")
        return

    # --- Registro de Log no Firestore ---
    log_collection = db.collection('system_logs')
    log_doc_ref = log_collection.document()
    log_data = {
        'run_id': str(uuid.uuid4()),
        'module': 'trigger-nlp-web',
        'target_doc_id': doc_id,
        'start_time': datetime.now(timezone.utc),
        'end_time': None,
        'status': 'processing',
        'details': f'Status "scraper_ok" detectado. Iniciando a invocação da API de NLP para o documento: {doc_id}'
    }
    log_doc_ref.set(log_data)
    logging.info(f"Status 'scraper_ok' detectado para {doc_id}. Log de sistema criado: {log_doc_ref.id}")

    try:
        id_token = get_auth_token()
        headers = {"Authorization": f"Bearer {id_token}"}
        target_url = f"{API_NLP_SERVICE_URL}/process/web/{doc_id}"

        logging.info(f"Invocando a API de NLP em: {target_url}")
        response = requests.post(target_url, headers=headers, timeout=300)
        response.raise_for_status()

        logging.info(f"API de NLP invocada com sucesso para o doc_id: {doc_id}. Resposta: {response.json()}")
        
        log_data.update({
            'end_time': datetime.now(timezone.utc),
            'status': 'success',
            'details': f'API de NLP invocada com sucesso. Status da resposta: {response.status_code}.'
        })

    except requests.exceptions.RequestException as e:
        error_message = f"Erro de HTTP/Rede ao invocar a API de NLP: {e}"
        logging.error(error_message)
        log_data.update({
            'end_time': datetime.now(timezone.utc),
            'status': 'failed',
            'details': error_message,
            'error_details': str(e.response.text) if e.response else 'No response from server'
        })
        raise

    except Exception as e:
        error_message = f"Ocorreu um erro inesperado: {e}"
        logging.error(error_message, exc_info=True)
        log_data.update({
            'end_time': datetime.now(timezone.utc),
            'status': 'failed',
            'details': error_message
        })
        raise

    finally:
        log_doc_ref.update(log_data)
        logging.info(f"Log de sistema finalizado para o doc_id: {doc_id} com status: {log_data['status']}")
