import os
import json
import time
import logging
import requests
import pika
import redis
import pymupdf  # fitz
from minio import Minio
from psycopg import connect
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- KONFIGURACJA ŚRODOWISKA ---
RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://guest:guest@rabbitmq:5672/')
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'minio:9000')
POSTGRES_URL = os.getenv('POSTGRES_URL', 'postgresql://user:password@postgres:5432/papers_db')
NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://neo4j:7687')
OLLAMA_URL = os.getenv('LLM_BASE_URL', 'http://ollama:11434')

# --- INICJALIZACJA KLIENTÓW ---
r_client = redis.from_url(REDIS_URL, decode_responses=True)

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=os.getenv('MINIO_ACCESS_KEY', 'minioadmin'),
    secret_key=os.getenv('MINIO_SECRET_KEY', 'minioadmin'),
    secure=False
)

# Upewniamy się, że bucket w MinIO istnieje
BUCKET_NAME = "papers"
if not minio_client.bucket_exists(BUCKET_NAME):
    minio_client.make_bucket(BUCKET_NAME)

neo4j_driver = GraphDatabase.driver(
    NEO4J_URI, 
    auth=(os.getenv('NEO4J_USER', 'neo4j'), os.getenv('NEO4J_PASSWORD', 'secretpassword'))
)

# --- FUNKCJE POMOCNICZE ---

def init_postgres():
    """Tworzy tabele w Postgresie, jeśli nie istnieją."""
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS papers (
                    id VARCHAR(50) PRIMARY KEY,
                    title TEXT NOT NULL,
                    published_date TIMESTAMP,
                    summary_raw TEXT,
                    tldr_ai TEXT,
                    pdf_minio_url TEXT,
                    status VARCHAR(20) DEFAULT 'NEW'
                )
            """)
            conn.commit()

def download_and_extract_pdf(pdf_url, paper_id):
    """Pobiera PDF, zapisuje w MinIO i wyciąga tekst z pierwszych 2 stron dla AI."""
    response = requests.get(pdf_url, stream=True)
    pdf_path = f"/tmp/{paper_id}.pdf"
    
    with open(pdf_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            
    # Zapis do MinIO
    minio_client.fput_object(BUCKET_NAME, f"{paper_id}.pdf", pdf_path)
    minio_url = f"http://{MINIO_ENDPOINT}/{BUCKET_NAME}/{paper_id}.pdf"
    
    # Ekstrakcja tekstu (tylko 2 pierwsze strony, żeby nie zapchać okna kontekstowego LLM)
    text_content = ""
    doc = pymupdf.open(pdf_path)
    for page_num in range(min(2, len(doc))):
        text_content += doc[page_num].get_text()
    
    os.remove(pdf_path)
    return minio_url, text_content

def ask_ollama(text):
    """Wysyła tekst do lokalnej Ollamy i prosi o ustrukturyzowany JSON."""
    prompt = f"""
    You are an expert Data Science researcher. Analyze the following text from a research paper's first pages.
    Extract the information and return ONLY a valid JSON object with the following schema:
    {{
        "tldr": "A 2-sentence executive summary of what this paper achieves",
        "institutions": ["List of universities or companies the authors belong to"],
        "tech_tags": ["List of specific algorithms, frameworks, or models used (e.g., PyTorch, CNN)"],
        "datasets": ["List of datasets mentioned (e.g., ImageNet)"]
    }}
    
    TEXT:
    {text[:4000]} # Ograniczamy na wszelki wypadek
    """
    
    response = requests.post(f"{OLLAMA_URL}/api/generate", json={
        "model": "llama3", # Upewnij się, że masz pobrany ten model w Ollamie
        "prompt": prompt,
        "format": "json",
        "stream": False
    })
    
    if response.status_code == 200:
        return json.loads(response.json()['response'])
    return None

# --- GŁÓWNA LOGIKA WORKERA ---

def process_message(ch, method, properties, body):
    data = json.loads(body)
    paper_id = data['id']
    logger.info(f"Rozpoczynam przetwarzanie: {paper_id}")

    # ==========================================
    # ETAP 1: FAST PATH (Błyskawiczny zapis z API)
    # ==========================================
    
    # 1.1 Zapis do PostgreSQL (Metadane)
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO papers (id, title, published_date, summary_raw, status)
                VALUES (%s, %s, %s, %s, 'PROCESSING')
                ON CONFLICT (id) DO NOTHING
            """, (paper_id, data['title'], data['published'], data['summary_raw']))
            conn.commit()

    # 1.2 Zapis do Neo4j (Podstawowy graf autorów i kategorii)
    with neo4j_driver.session() as session:
        cypher_query = """
        MERGE (p:Paper {id: $id, title: $title})
        WITH p
        UNWIND $authors AS author_name
        MERGE (a:Author {name: author_name})
        MERGE (a)-[:WROTE]->(p)
        WITH p
        UNWIND $categories AS cat_name
        MERGE (c:Category {name: cat_name})
        MERGE (p)-[:BELONGS_TO]->(c)
        """
        session.run(cypher_query, id=paper_id, title=data['title'], authors=data['authors'], categories=data['categories'])

    # 1.3 Publikacja na Redis (Natychmiast na Frontend)
    r_client.publish('paper_events', json.dumps({"event": "NEW_PAPER", "id": paper_id, "title": data['title']}))

    # ==========================================
    # ETAP 2: SLOW PATH (Pobieranie PDF + AI)
    # ==========================================
    try:
        logger.info(f"[{paper_id}] Pobieranie PDF i ekstrakcja tekstu...")
        minio_url, pdf_text = download_and_extract_pdf(data['pdf_url'], paper_id)
        
        logger.info(f"[{paper_id}] Analiza LLM w Ollama...")
        ai_data = ask_ollama(pdf_text)
        
        if ai_data:
            # 2.1 Aktualizacja w Postgres (Wyniki AI i link MinIO)
            with connect(POSTGRES_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE papers SET tldr_ai = %s, pdf_minio_url = %s, status = 'ENRICHED' WHERE id = %s
                    """, (ai_data.get('tldr', ''), minio_url, paper_id))
                    conn.commit()

            # 2.2 Aktualizacja w Neo4j (Głębokie tagi, instytucje, dane)
            with neo4j_driver.session() as session:
                ai_cypher = """
                MATCH (p:Paper {id: $id})
                
                // Dodawanie instytucji
                WITH p
                UNWIND $institutions AS inst_name
                MERGE (i:Institution {name: inst_name})
                MERGE (p)-[:AFFILIATED_WITH]->(i)
                
                // Dodawanie szczegółowych tagów technologicznych
                WITH p
                UNWIND $tech_tags AS tech_name
                MERGE (t:TechTag {name: tech_name})
                MERGE (p)-[:USES_TECH]->(t)
                
                // Dodawanie użytych zbiorów danych
                WITH p
                UNWIND $datasets AS ds_name
                MERGE (d:Dataset {name: ds_name})
                MERGE (p)-[:TESTED_ON]->(d)
                """
                session.run(ai_cypher, id=paper_id, 
                            institutions=ai_data.get('institutions', []),
                            tech_tags=ai_data.get('tech_tags', []),
                            datasets=ai_data.get('datasets', []))

            # 2.3 Publikacja na Redis (Frontend odświeża kartę pracy o szczegóły)
            r_client.publish('paper_events', json.dumps({"event": "PAPER_ENRICHED", "id": paper_id}))
            logger.info(f"[{paper_id}] Sukces! Praca wzbogacona przez AI.")
            
    except Exception as e:
        logger.error(f"[{paper_id}] Błąd podczas analizy PDF/AI: {e}")
        with connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE papers SET status = 'FAILED' WHERE id = %s", (paper_id,))
                conn.commit()

    # Potwierdzamy do RabbitMQ, że skończyliśmy zadanie (usuwa z kolejki)
    ch.basic_ack(delivery_tag=method.delivery_tag)

def start_consuming():
    init_postgres()
    while True:
        try:
            params = pika.URLParameters(RABBITMQ_URL)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue='paper_tasks', durable=True)
            
            # Pobieramy tylko 1 wiadomość na raz (ważne dla długich zadań AI)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue='paper_tasks', on_message_callback=process_message)
            
            logger.info("Oczekuję na wiadomości z RabbitMQ...")
            channel.start_consuming()
        except Exception as e:
            logger.error(f"Błąd połączenia z RabbitMQ: {e}. Ponawiam za 5s...")
            time.sleep(5)

if __name__ == "__main__":
    start_consuming()