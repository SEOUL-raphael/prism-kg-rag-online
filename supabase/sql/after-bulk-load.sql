-- Run this in Supabase SQL Editor after chunks.jsonl has finished loading.

create extension if not exists pg_trgm;
create index if not exists chunks_text_trgm on public.chunks using gin (text gin_trgm_ops);
analyze public.projects;
analyze public.reports;
analyze public.files;
analyze public.kg_nodes;
analyze public.kg_edges;
analyze public.chunks;
notify pgrst, 'reload schema';
