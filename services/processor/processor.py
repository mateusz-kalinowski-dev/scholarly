import os
import json
import time
import logging
import requests
import pika
import redis
import tarfile
import gzip
import io
import re
from minio import Minio
from psycopg import connect
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- KONFIGURACJA ŚRODOWISKA ---
RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://guest:guest@rabbitmq:5672/')
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'minio:9000')
POSTGRES_URL = os.getenv('POSTGRES_URL', 'postgresql://admin:admin@postgres:5432/papers_db')
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

BUCKET_NAME = "papers"
if not minio_client.bucket_exists(BUCKET_NAME):
    minio_client.make_bucket(BUCKET_NAME)

neo4j_driver = GraphDatabase.driver(
    NEO4J_URI, 
    auth=(os.getenv('NEO4J_USER', 'neo4j'), os.getenv('NEO4J_PASSWORD', 'secretpassword'))
)

# --- FUNKCJE POMOCNICZE ---

def wait_for_ollama_models(models_required, host=OLLAMA_URL):
    logger.info(f"Sprawdzam dostępność Ollamy i modeli: {models_required}...")
    while True:
        try:
            response = requests.get(f"{host}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                available_models = [model["name"] for model in data.get("models", [])]
                missing_models = [req for req in models_required if not any(req in avail for avail in available_models)]
                
                if not missing_models:
                    logger.info("Wszystkie wymagane modele AI są gotowe! Można startować workera.")
                    return True
                else:
                    logger.warning(f"Ollama odpowiada, ale brakuje modeli: {missing_models}. Czekam...")
            else:
                logger.warning(f"Ollama zwróciła błąd HTTP {response.status_code}. Czekam...")
        except requests.exceptions.RequestException:
            logger.warning("Brak połączenia z Ollamą. Kontener może jeszcze się uruchamiać. Czekam...")
        time.sleep(10)

def init_postgres():
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            cur.execute("""
                CREATE TABLE IF NOT EXISTS papers (
                    id VARCHAR(50) PRIMARY KEY,
                    title TEXT NOT NULL,
                    published_date TIMESTAMP,
                    summary_raw TEXT,
                    tldr_ai TEXT,
                    pdf_minio_url TEXT, -- Zostawiamy tę nazwę w bazie dla kompatybilności, ale wrzucimy tu link .txt
                    embedding VECTOR(768),
                    status VARCHAR(20) DEFAULT 'NEW'
                )
            """)
            conn.commit()

def get_embedding(text):
    response = requests.post(f"{OLLAMA_URL}/api/embeddings", json={
        "model": "nomic-embed-text", 
        "prompt": text[:2000] # Do wektoryzacji sam początek zazwyczaj wystarcza
    })
    if response.status_code == 200:
        return response.json().get('embedding')
    return None

def download_and_extract_tex(source_url, paper_id):
    """Pobiera paczkę źródłową arXiv (e-print), wypakowuje w locie i wyciąga czysty tekst z plików .tex"""
    year = f"20{paper_id[0:2]}"
    month = paper_id[2:4]
    object_name = f"{year}/{month}/{paper_id}.txt"
    
    # 1. Pobieranie danych do pamięci RAM (bardzo szybkie)
    response = requests.get(source_url)
    file_bytes = io.BytesIO(response.content)
    text_content = ""
    
    # 2. Próba rozpakowania jako tar.gz (standard arXiv)
    try:
        with tarfile.open(fileobj=file_bytes, mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".tex"):
                    f = tar.extractfile(member)
                    if f:
                        text_content += f.read().decode('utf-8', errors='ignore') + "\n"
    except tarfile.ReadError:
        # Czasami (szczególnie starsze prace) to po prostu skompresowany pojedynczy plik .gz
        file_bytes.seek(0)
        try:
            with gzip.GzipFile(fileobj=file_bytes) as gz:
                text_content = gz.read().decode('utf-8', errors='ignore')
        except OSError:
            # W ostateczności to surowy tekst
            text_content = response.text

    # 3. Podstawowe czyszczenie kodu LaTeX (usuwanie komentarzy)
    text_content = re.sub(r'(?m)^%.*$', '', text_content)
    
    # Jeśli paczka nie miała tekstu (np. to był sam Word / PDF), robimy awaryjny pusty string
    if not text_content.strip():
        logger.warning(f"[{paper_id}] Brak plików .tex w paczce źródłowej.")
        text_content = "Brak dostępnego źródła tekstowego."

    # 4. Zapis wyciągniętego tekstu do MinIO
    text_bytes = text_content.encode('utf-8')
    minio_client.put_object(
        BUCKET_NAME, 
        object_name, 
        io.BytesIO(text_bytes), 
        length=len(text_bytes),
        content_type="text/plain"
    )
    
    minio_url = f"http://{MINIO_ENDPOINT}/{BUCKET_NAME}/{object_name}"
    return minio_url, text_content

def ask_ollama(text):
    prompt = f"""
    You are an expert Data Science researcher. Analyze the following text from a research paper.
    Extract the information and return ONLY a valid JSON object with the following schema:
    {{
        "tldr": "A 2-sentence executive summary of what this paper achieves",
        "institutions": ["List of universities or companies the authors belong to"],
        "problem_solved": "A short, 3-7 word description of the specific challenge being addressed.",
        "tech_tools": ["List of specific algorithms, frameworks, or models used"],
        "datasets": ["List of datasets mentioned"]
    }}
    
    TEXT:
    {text[:60000]} 
    """
    
    # UWAGA DO LIMITU WYŻEJ:
    # Wrzucamy do 60 000 znaków (ok. 15 tys. tokenów), żeby model nie rzucił 
    # błędem "Context window exceeded", co może się zdarzyć przy bardzo długich pracach.
    
    response = requests.post(f"{OLLAMA_URL}/api/generate", json={
        "model": "gemma4:e2b", 
        "prompt": prompt,
        "format": "json",
        "stream": False,
        "options": {
            "num_ctx": 30000 # <-- DODAJEMY TO: Zwiększamy limit kontekstu
        }
    })
    
    if response.status_code == 200:
        return json.loads(response.json()['response'])
    return None

# --- GŁÓWNA LOGIKA WORKERA ---

def process_message(ch, method, properties, body):
    data = json.loads(body)
    paper_id = data['id']
    logger.info(f"Rozpoczynam przetwarzanie: {paper_id}")

    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO papers (id, title, published_date, summary_raw, status)
                VALUES (%s, %s, %s, %s, 'PROCESSING')
                ON CONFLICT (id) DO NOTHING
            """, (paper_id, data['title'], data['published'], data['summary_raw']))
            conn.commit()

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

    r_client.publish('paper_events', json.dumps({"event": "NEW_PAPER", "id": paper_id, "title": data['title']}))

    try:
        logger.info(f"[{paper_id}] Pobieranie e-print (TeX) i ekstrakcja tekstu...")
        # Zmieniono z pdf_url na source_url z kolejki RabbitMQ
        minio_url, raw_text = download_and_extract_tex(data['source_url'], paper_id)
        
        logger.info(f"[{paper_id}] Analiza LLM całej pracy w Ollama...")
        ai_data = ask_ollama(raw_text)
        
        if ai_data:
            logger.info(f"[{paper_id}] Generowanie wektora...")
            vector_embedding = get_embedding(raw_text)

            with connect(POSTGRES_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE papers 
                        SET tldr_ai = %s, 
                            pdf_minio_url = %s, 
                            embedding = %s::vector,
                            status = 'ENRICHED' 
                        WHERE id = %s
                    """, (
                        ai_data.get('tldr', ''), 
                        minio_url, 
                        vector_embedding, 
                        paper_id
                    ))
                    conn.commit()

            with neo4j_driver.session() as session:
                ai_cypher = """
                MATCH (p:Paper {id: $id})
                WITH p
                UNWIND $institutions AS inst_name
                MERGE (i:Institution {name: inst_name})
                MERGE (p)-[:AFFILIATED_WITH]->(i)
                WITH p
                UNWIND $tech_tags AS tech_name
                MERGE (t:TechTag {name: tech_name})
                MERGE (p)-[:USES_TECH]->(t)
                WITH p
                UNWIND $datasets AS ds_name
                MERGE (d:Dataset {name: ds_name})
                MERGE (p)-[:TESTED_ON]->(d)
                """
                session.run(ai_cypher, id=paper_id, 
                            institutions=ai_data.get('institutions', []),
                            tech_tags=ai_data.get('tech_tools', []),
                            datasets=ai_data.get('datasets', []))

            r_client.publish('paper_events', json.dumps({"event": "PAPER_ENRICHED", "id": paper_id}))
            logger.info(f"[{paper_id}] Sukces! Praca wzbogacona przez AI.")
            
    except Exception as e:
        logger.error(f"[{paper_id}] Błąd podczas analizy TeX/AI: {e}")
        with connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE papers SET status = 'FAILED' WHERE id = %s", (paper_id,))
                conn.commit()

    ch.basic_ack(delivery_tag=method.delivery_tag)

def start_consuming():
    init_postgres()
    while True:
        try:
            params = pika.URLParameters(RABBITMQ_URL)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue='paper_tasks', durable=True)
            channel.basic_qos(prefetch_count=1)
            channel.basic_consume(queue='paper_tasks', on_message_callback=process_message)
            
            logger.info("Oczekuję na wiadomości z RabbitMQ...")
            channel.start_consuming()
        except Exception as e:
            logger.error(f"Błąd połączenia z RabbitMQ: {e}. Ponawiam za 5s...")
            time.sleep(5)

if __name__ == "__main__":
    WYMAGANE_MODELE = ["gemma4:e2b", "nomic-embed-text"]
    wait_for_ollama_models(WYMAGANE_MODELE)
    start_consuming()