-- Run this in Supabase SQL Editor before loading the large chunks.jsonl file.
-- The trigram GIN index is useful for search, but it makes bulk inserts time out.

drop index if exists public.chunks_text_trgm;
notify pgrst, 'reload schema';
