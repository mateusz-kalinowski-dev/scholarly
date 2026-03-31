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

def fetch_arxiv_papers(query="cat:cs.LG OR cat:cs.AI OR cat:cs.DS", max_results=10):
    """Odpytuje API arXiv o najnowsze prace"""
    # Sortujemy od najnowszych
    base_url = "http://export.arxiv.org/api/query?"
    params = (
        f"search_query={query}&"
        f"sortBy=submittedDate&"
        f"sortOrder=descending&"
        f"max_results={max_results}"
    )
    
    response = requests.get(base_url + params)
    if response.status_code == 200:
        return feedparser.parse(response.content)
    else:
        logger.error(f"Błąd API arXiv: {response.status_code}")
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
            
            # ArXiv zwraca wyniki od najnowszych, więc lecimy od tyłu (od najstarszych w paczce)
            # aby zachować kolejność chronologiczną
            logger.info(f"Dostępne pola w API to: {list(feed.entries[0].keys())}")
            for entry in reversed(feed.entries):
                published_time = entry.published # Format: '2024-03-20T15:30:00Z'
                
                # Jeśli praca jest nowsza niż nasz checkpoint, procesujemy ją
                if not last_checkpoint or published_time > last_checkpoint:
                    
                    paper_data = {
                        "id": entry.id.split('/')[-1], # Wyciąga samo ID z URL
                        "title": entry.title.replace('\n', ' '),
                        "authors": [a.name for a in entry.authors],
                        "pdf_url": entry.link.replace('abs', 'pdf') + ".pdf",
                        "published": published_time,
                        
                        # NOWE POLA:
                        "updated": entry.get('updated', published_time), # Data ostatniej rewizji pracy
                        "primary_category": entry.arxiv_primary_category['term'] if 'arxiv_primary_category' in entry else None, # np. 'cs.LG'
                        "categories": [tag['term'] for tag in entry.get('tags', [])], # Lista wszystkich kategorii, np. ['cs.LG', 'stat.ML']
                        
                        "summary_raw": entry.summary
                    }

                    paper_data2 = {
                        "id": entry.id.split('/')[-1], # Wyciąga samo ID z URL
                        "title": entry.title.replace('\n', ' '),
                        "authors": [a.name for a in entry.authors],
                        "pdf_url": entry.link.replace('abs', 'pdf') + ".pdf",
                        "published": published_time,
                        "updated": entry.get('updated', published_time), # Data ostatniej rewizji pracy
                        "primary_category": entry.arxiv_primary_category['term'] if 'arxiv_primary_category' in entry else None, # np. 'cs.LG'
                        "categories": [tag['term'] for tag in entry.get('tags', [])], # Lista wszystkich kategorii, np. ['cs.LG', 'stat.ML']
                        "summary_raw": entry.summary,
                        # nowe
                        #"guidislink": entry.get('guidislink', False), # Czasami arXiv dodaje to pole, które mówi czy ID jest linkiem (zazwyczaj True)
                        #'title_detail': entry.get('title_detail', {}), # Szczegóły dotyczące tytułu, np. typ (text/plain) i język
                        #'updated_parsed': entry.get('updated_parsed', None), # Data aktualizacji w formacie strukturalnym (time.struct_time) - może być przydatna do porównań dat
                        #'links': entry.get('links', []), # Lista wszystkich linków związanych z pracą, może zawierać dodatkowe zasoby oprócz PDF (np. DOI, strona HTML)
                        'summary_detail': entry.get('summary_detail', {}), # Szczegóły dotyczące streszczenia, podobnie jak title_detail
                        #'author_detail': entry.get('author_detail', []), # Szczegóły dotyczące autorów, może zawierać dodatkowe informacje o każdym autorze (np. email, afiliacja)
                        #'author': entry.get('author', None) # Pole 'author' jest czasami dostępne jako pojedynczy string, mimo że 'authors' jest listą - warto to mieć na uwadze
                    }

                    # 3. Wyślij zadanie do RabbitMQ
                    channel.basic_publish(
                        exchange='',
                        routing_key='paper_tasks',
                        body=json.dumps(paper_data2),
                        properties=pika.BasicProperties(delivery_mode=2) # Wiadomość trwała
                    )
                    
                    logger.info(f"Wysłano do kolejki: {paper_data['id']} - {paper_data['title'][:50]}...")
                    newest_timestamp_in_batch = published_time

            # 4. Zaktualizuj checkpoint w Redisie na najnowszą datę jaką widzieliśmy
            if newest_timestamp_in_batch:
                r_client.set(CHECKPOINT_KEY, newest_timestamp_in_batch)
                logger.info(f"Zaktualizowano checkpoint na: {newest_timestamp_in_batch}")
        
        # 5. Czekaj przed kolejnym sprawdzeniem (np. 1 godzina)
        # W celach testowych możesz ustawić 60 sekund
        logger.info("Zasypiam na 1 godzinę...")
        time.sleep(3600)

if __name__ == "__main__":
    run_scraper()