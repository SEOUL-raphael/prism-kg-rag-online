-- Run this in Supabase SQL Editor after chunks.jsonl has finished loading.

create extension if not exists pg_trgm;
create index if not exists files_status_idx on public.files (status);
create index if not exists chunks_file_id_idx on public.chunks (file_id);
create index if not exists chunks_text_trgm on public.chunks using gin (text gin_trgm_ops);
analyze public.projects;
analyze public.reports;
analyze public.files;
analyze public.kg_nodes;
analyze public.kg_edges;
analyze public.chunks;
notify pgrst, 'reload schema';
