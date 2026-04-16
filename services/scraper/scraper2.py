import os
import time
import json
import logging
import requests
import feedparser
import pika
import redis
from datetime import datetime

# Konfiguracja logowania
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Ładowanie zmiennych środowiskowych (w Dockerze przyjdą z docker-compose)
RABBITMQ_URL = os.getenv('RABBITMQ_URL', 'amqp://guest:guest@rabbitmq:5672/')
REDIS_URL = os.getenv('REDIS_URL', 'redis://redis:6379/0')
CHECKPOINT_KEY = "scraper:last_paper_timestamp"

# Połączenie z Redisem
r_client = redis.from_url(REDIS_URL, decode_responses=True)

def connect_rabbitmq():
    """Łączy się z RabbitMQ z mechanizmem retry (bo RabbitMQ wstaje chwilę dłużej)"""
    while True:
        try:
            params = pika.URLParameters(RABBITMQ_URL)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue='paper_tasks', durable=True)
            return connection, channel
        except Exception as e:
            logger.warning(f"Błąd połączenia z RabbitMQ: {e}. Ponawiam za 5s...")
            time.sleep(5)

def fetch_arxiv_papers(query="cat:cs.LG+OR+cat:cs.AI", max_results=100):
    """
    Odpytuje API arXiv o najnowsze prace.
    Zoptymalizowane pod kątem unikania błędu 503.
    """
    base_url = "http://export.arxiv.org/api/query?"
    
    # 1. Kodowanie spacji: arXiv preferuje '%20' lub '+' w zapytaniach zamiast zwykłych spacji.
    safe_query = query.replace(' ', '+')
    
    params = (
        f"search_query={safe_query}&"
        f"sortBy=submittedDate&"
        f"sortOrder=descending&"
        f"start=0&" # W przyszłości możesz to zmieniać do paginacji
        f"max_results={max_results}" # Lepiej pobrać 100 na raz i przetwarzać je lokalnie
    )
    
    max_retries = 3
    base_delay = 5
    
    for attempt in range(max_retries):
        try:
            # Bardzo specyficzny User-Agent pokazujący "dobre chęci" akademickie
            headers = {
                'User-Agent': 'mailto:twoj.email@student.uczelnia.pl - ArxivRAG/1.0 (Polite Scraper)'
            }
            
            logger.info(f"Odpytywanie arXiv API (Próba {attempt+1}): {base_url}{params}")
            
            # Timeout na 30 sekund (arXiv bywa wolny)
            response = requests.get(base_url + params, headers=headers, timeout=30)
            
            if response.status_code == 200:
                time.sleep(3) # Bezwzględnie wymagane przez arXiv
                return feedparser.parse(response.content)
            
            else:
                delay = base_delay * (2 ** attempt)
                logger.warning(f"arXiv zwrócił błąd {response.status_code}. Czekam {delay}s...")
                time.sleep(delay)
                
        except Exception as e:
            delay = base_delay * (2 ** attempt)
            logger.error(f"Błąd sieci: {e}. Czekam {delay}s...")
            time.sleep(delay)
            
    return None

def run_scraper():
    logger.info("Uruchamianie scrapera arXiv...")
    connection, channel = connect_rabbitmq()

    while True:
        # 1. Pobierz timestamp ostatnio przetworzonej pracy z Redisa
        last_checkpoint = r_client.get(CHECKPOINT_KEY)
        logger.info(f"Ostatni checkpoint: {last_checkpoint}")

        # 2. Pobierz nowości z arXiv
        feed = fetch_arxiv_papers()
        
        if feed and feed.entries:
            newest_timestamp_in_batch = None
            
            # ArXiv zwraca wyniki od najnowszych, więc lecimy od tyłu
            for entry in reversed(feed.entries):
                published_time = entry.published
                
                # Jeśli praca jest nowsza niż nasz checkpoint, procesujemy ją
                if not last_checkpoint or published_time > last_checkpoint:
                    
                    paper_id = entry.id.split('/')[-1]
                    
                    # Generowanie URL do pobrania źródła (e-print) zamist PDF
                    # entry.link zazwyczaj wygląda tak: http://arxiv.org/abs/2403.01234v1
                    # URL źródła (TeX) wygląda tak: http://arxiv.org/e-print/2403.01234v1
                    source_url = entry.link.replace('/abs/', '/e-print/')
                    
                    paper_data = {
                        "id": paper_id,
                        "title": entry.title.replace('\n', ' '),
                        "authors": [a.name for a in entry.authors],
                        "source_url": source_url,  # Zmieniono z pdf_url
                        "published": published_time,
                        "updated": entry.get('updated', published_time),
                        "primary_category": entry.arxiv_primary_category['term'] if 'arxiv_primary_category' in entry else None,
                        "categories": [tag['term'] for tag in entry.get('tags', [])],
                        "summary_raw": entry.summary,
                        'summary_detail': entry.get('summary_detail', {})
                    }

                    # 3. Wyślij zadanie do RabbitMQ
                    channel.basic_publish(
                        exchange='',
                        routing_key='paper_tasks',
                        body=json.dumps(paper_data),
                        properties=pika.BasicProperties(delivery_mode=2)
                    )
                    
                    logger.info(f"Wysłano do kolejki: {paper_data['id']} - {paper_data['title'][:50]}...")
                    newest_timestamp_in_batch = published_time

            # 4. Zaktualizuj checkpoint w Redisie na najnowszą datę jaką widzieliśmy
            if newest_timestamp_in_batch:
                r_client.set(CHECKPOINT_KEY, newest_timestamp_in_batch)
                logger.info(f"Zaktualizowano checkpoint na: {newest_timestamp_in_batch}")
        
        logger.info("Zasypiam na 1 godzinę...")
        time.sleep(3600)

if __name__ == "__main__":
    run_scraper()