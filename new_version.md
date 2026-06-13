uzyjemy do embedingów nowego modelu w ollama: `bge-m3`
migracja na nową baze danych, któa zawiera `pg_search` czyli postgres wersja paradedb/paradedb:latest lub pasujący do migracji 
vectory mają miec wymiar 1024 teraz

Musisz upewnić się, że Postgres indeksuje do wyszukiwania tekstowego zarówno zawartość chunka, jak i wyciągnięte słowa kluczowe.

Dla wektorów (HNSW): ```sql
CREATE INDEX ON chunks USING hnsw (embedding vector_cosine_ops);

Dla słów kluczowych (GIN):

SQL
CREATE INDEX ON chunks USING gin (text_search);


Krok 6: Złote Zapytanie (Hybrydowe Wyszukiwanie SQL)
Jak wygląda moment, gdy użytkownik zadaje pytanie (np. "Jak wyliczono zbieżność w modelu?")?

Wysyłasz zapytanie użytkownika do Ollamy (BGE-M3) i otrzymujesz z powrotem wektor (nazwijmy go $query_vector).

Zamieniasz zapytanie użytkownika na format tekstowy dla Postgresa (np. 'zbieżność & model').

Uderzasz do Postgresa jednym, potężnym zapytaniem SQL, które ocenia dopasowanie obu wartości i podmienia Dziecko na Rodzica:

SQL
WITH child_matches AS (
    SELECT 
        parent_id,
        content,
        -- Obliczamy odległość wektorową (im bliżej 0, tym lepiej)
        (embedding <=> $query_vector) AS vector_distance,
        -- Obliczamy trafność tekstową BM25-lite
        ts_rank(text_search, to_tsquery('english', 'zbieżność & model')) AS text_score
    FROM chunks
    WHERE parent_id IS NOT NULL -- Szukamy tylko w precyzyjnych dzieciach
    -- Możesz tu dodać filtrowanie merytoryczne: AND text_score > 0.1
    ORDER BY vector_distance ASC
    LIMIT 10
)

-- Teraz dla najlepszych Dzieci, wyciągamy ich pełnych Rodziców
SELECT 
    p.content AS full_context,
    c.vector_distance,
    c.text_score
FROM child_matches c
JOIN chunks p ON c.parent_id = p.chunk_id
ORDER BY (c.text_score - c.vector_distance) DESC; -- Prosta fuzja wyników

Krok 7: Przekazanie do LLM-a
Pełne bloki tekstu (full_context z Rodziców), które wypluł Postgres, pakujesz do prompta systemowego swojego dużego modelu (np. DeepSeek) z instrukcją: "Na podstawie poniższych fragmentów kodu naukowego odpowiedz na pytanie użytkownika...".

Ten setup to prawdziwy "czołg" w świecie RAG-ów. Łączy chirurgiczną precyzję małych chunków wektorowych BGE-M3 z siłą szerokiego kontekstu i niezawodnością wyszukiwania słów kluczowych bezpośrednio w Postgresie.

2. Hybrydowe Wyszukiwanie (Hybrid Search)
Sama baza wektorowa nie wystarczy. Wektory świetnie radzą sobie z kontekstem i synonimami, ale zawodzą przy szukaniu konkretnych numerów seryjnych, ID produktów czy unikalnych nazw własnych.

Połączenie potęg: Połącz Dense Retrieval (gęste wektory, np. Cohere Embed, OpenAI text-embedding-3) z Sparse Retrieval (wyszukiwanie słów kluczowych, np. BM25).

Grafy Wiedzy (Knowledge Graphs): Aby osiągnąć absolutny szczyt precyzji, połącz wektory z grafem wiedzy (GraphRAG). Pozwala to systemowi rozumieć relacje między obiektami (np. „Firma X kupiła Firmę Y, której prezesem jest Z”).

Bezkompromisowe Zarządzanie Kontekstem (Reranking & Filtering)
Bazy danych często zwracają dokumenty, które są matematycznie podobne, ale merytorycznie bezużyteczne. Musisz je przesiać.

Reranking (Ponowne ocenianie): To absolutny game-changer dla precyzji. Użyj zaawansowanego modelu rerankującego (np. Cohere Rerank, BGE-Reranker). Działa on wolniej niż baza wektorowa, ale potrafi niesamowicie precyzyjnie ocenić, które 3 z 50 znalezionych fragmentów faktycznie odpowiadają na pytanie.

Metadata Filtering: Zanim zaczniesz szukać wektorowo, odfiltruj bazę po twardych danych (np. „szukaj tylko w dokumentach z roku 2025”, „tylko dla działu prawnego”).

Architektura Agentowa i Self-RAG (Autokorekta)
Najbardziej precyzyjne systemy potrafią ocenić samych siebie przed pokazaniem odpowiedzi użytkownikowi.

Query Transformation: Użytkownicy zadają chaotyczne pytania. Użyj małego, szybkiego LLM-a do „przepisania” zapytania (Query Rewriting), wygenerowania kilku jego wersji (Query Expansion) lub rozbicia złożonego pytania na pod-pytania (Sub-query Generation).

Self-Correction Loop (Pętla samooceny):

System pobiera dokumenty.

LLM ocenia: „Czy te dokumenty w ogóle zawierają odpowiedź?” (Jeśli nie -> szuka ponownie z innym zapytaniem).

LLM generuje odpowiedź.

Co jest do CAŁKOWITEJ ZMIANY (Krytyczny błąd):
Funkcja clean_text to obecnie „rzeźnik” dla Twoich danych naukowych.
Spójrz na te trzy linijki:

Python
text = re.sub(r"\\begin\{[^}]+\}.*?\\end\{[^}]+\}", "", text, flags=re.DOTALL) # USUWA RÓWNANIA, TABELE I ALGORYTMY!
text = re.sub(r"\$[^$]+\$", " ", text) # USUWA CAŁĄ MATEMATYKĘ W TEKŚCIE (np. "dla x > 5")!
text = re.sub(r"\\\[[\s\S]*?\\\]", " ", text) # USUWA RÓWNANIA BLOKOWE!
Twój obecny kod kasuje z prac naukowych całą matematykę i logikę, zostawiając sam surowy, opisowy tekst. Jeśli wyślesz tak wyczyszczony tekst do BGE-M3, model nie będzie miał pojęcia, o jakim wzorze mowa.

Jak to naprawić? (Nowa wizja)
Zamiast brutalnie usuwać matematykę, musimy ją wyizolować i potraktować jako relikwię (tzw. "Święte Chunki").

clean_text powinno usuwać tylko śmieci formatujące (komentarze %, \newpage, nagłówki obrazków \begin{figure}).

Równania matematyczne i tabele muszą zostać nietknięte jako część tekstu Rodzica, a następnie wycięte jako oddzielne Dzieci do wektoryzacji.

Korpus v2: **11 530** prac z `paper_embeddings`, **~398k** child chunków.

### Pipeline wzbogacenia wyszukiwania
```powershell
# 1) KeyBERT backfill (keywords + keywords_keybert → trigger → search_text)
docker compose build keybert-backfill
docker compose run -d --name scholarly_keybert `
  -v scholarly_hf_cache:/cache/huggingface `
  -e POSTGRES_V2_URL=postgresql://admin:admin@postgres_v2:5432/papers_db_v2 `
  keybert-backfill

# 2) Po zakończeniu backfillu — indeksy od zera
docker compose run --rm -e POSTGRES_V2_URL=postgresql://admin:admin@postgres_v2:5432/papers_db_v2 `
  processor python rebuild_indexes_v2.py

# 3) API v2 + Self-RAG (kolejny krok)
```

Reprocess jednej pracy: `python rechunk_v2.py --arxiv-id 2605.08376`