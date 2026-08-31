-- keywords KeyBERT (backfill: services/processor/backfill_keywords_keybert.py)
ALTER TABLE chunks
    ADD COLUMN IF NOT EXISTS keywords_keybert TEXT[] NOT NULL DEFAULT '{}';

CREATE OR REPLACE FUNCTION chunks_sync_text_search() RETURNS trigger AS $$
BEGIN
    NEW.search_text := trim(both from
        NEW.content || ' ' ||
        coalesce(array_to_string(NEW.keywords, ' '), '') || ' ' ||
        coalesce(array_to_string(NEW.keywords_keybert, ' '), '')
    );
    NEW.text_search := to_tsvector('english', NEW.search_text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Odśwież text_search dla istniejących childów (może chwilę potrwać)
UPDATE chunks
SET keywords = keywords
WHERE chunk_role = 'child';
