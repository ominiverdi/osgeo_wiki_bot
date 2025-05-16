CREATE OR REPLACE FUNCTION update_chunk_tsv()
RETURNS TRIGGER AS $$
BEGIN
  NEW.tsv = to_tsvector('english', NEW.chunk_text);
  RETURN NEW;
END
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_chunk_tsv_trigger
BEFORE INSERT OR UPDATE ON page_chunks
FOR EACH ROW EXECUTE FUNCTION update_chunk_tsv();