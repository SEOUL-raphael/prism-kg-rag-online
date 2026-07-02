create extension if not exists pg_trgm;

create table if not exists public.projects (
  research_id text primary key,
  research_name text,
  organ_name text,
  researcher_name text,
  charge_person_department text,
  charge_person_phone_no text,
  biz_name text,
  research_start_date text,
  research_end_date text,
  brm_biz_name text,
  research_outline text,
  issued_year text,
  updated_at timestamptz default now()
);

create table if not exists public.reports (
  id text primary key,
  research_id text references public.projects(research_id) on delete cascade,
  title text,
  table_contents text,
  summary text,
  keyword text,
  issued_year text,
  updated_at timestamptz default now()
);

create table if not exists public.files (
  id text primary key,
  research_id text references public.projects(research_id) on delete cascade,
  source_section text,
  file_type text,
  file_name text,
  file_size text,
  media_type text,
  sha256 text,
  size integer,
  status text,
  markdown_chars integer,
  updated_at timestamptz default now()
);

create table if not exists public.kg_nodes (
  id text primary key,
  kind text,
  label text,
  data jsonb default '{}'::jsonb,
  updated_at timestamptz default now()
);

create table if not exists public.kg_edges (
  id text primary key,
  from_id text references public.kg_nodes(id) on delete cascade,
  to_id text references public.kg_nodes(id) on delete cascade,
  kind text,
  data jsonb default '{}'::jsonb,
  updated_at timestamptz default now()
);

create table if not exists public.chunks (
  id bigint primary key,
  document_id text,
  chunk_index integer,
  research_id text references public.projects(research_id) on delete cascade,
  file_id text references public.files(id) on delete set null,
  title text,
  organ_name text,
  file_name text,
  text text not null,
  metadata jsonb default '{}'::jsonb,
  updated_at timestamptz default now()
);

create table if not exists public.rag_query_logs (
  id bigint generated always as identity primary key,
  user_id uuid references auth.users(id) on delete set null,
  question text not null,
  answer_chars integer default 0,
  evidence_count integer default 0,
  created_at timestamptz default now()
);

create index if not exists projects_research_name_trgm on public.projects using gin (research_name gin_trgm_ops);
create index if not exists projects_organ_name_idx on public.projects (organ_name);
create index if not exists files_research_id_idx on public.files (research_id);
create index if not exists chunks_research_id_idx on public.chunks (research_id);
create index if not exists chunks_text_trgm on public.chunks using gin (text gin_trgm_ops);
create index if not exists kg_nodes_kind_label_idx on public.kg_nodes (kind, label);
create index if not exists kg_nodes_label_trgm on public.kg_nodes using gin (label gin_trgm_ops);
create index if not exists kg_edges_from_idx on public.kg_edges (from_id);
create index if not exists kg_edges_to_idx on public.kg_edges (to_id);

alter table public.projects enable row level security;
alter table public.reports enable row level security;
alter table public.files enable row level security;
alter table public.kg_nodes enable row level security;
alter table public.kg_edges enable row level security;
alter table public.chunks enable row level security;
alter table public.rag_query_logs enable row level security;

grant usage on schema public to anon, authenticated, service_role;
grant select on table
  public.projects,
  public.reports,
  public.files,
  public.kg_nodes,
  public.kg_edges,
  public.chunks
to authenticated;
grant insert, select on table public.rag_query_logs to authenticated;
grant all privileges on table
  public.projects,
  public.reports,
  public.files,
  public.kg_nodes,
  public.kg_edges,
  public.chunks,
  public.rag_query_logs
to service_role;
grant usage, select on sequence public.rag_query_logs_id_seq to authenticated, service_role;

drop policy if exists "authenticated can read projects" on public.projects;
drop policy if exists "authenticated can read reports" on public.reports;
drop policy if exists "authenticated can read files" on public.files;
drop policy if exists "authenticated can read kg_nodes" on public.kg_nodes;
drop policy if exists "authenticated can read kg_edges" on public.kg_edges;
drop policy if exists "authenticated can read chunks" on public.chunks;
drop policy if exists "authenticated can insert own rag logs" on public.rag_query_logs;
drop policy if exists "authenticated can read own rag logs" on public.rag_query_logs;

create policy "authenticated can read projects" on public.projects for select to authenticated using (true);
create policy "authenticated can read reports" on public.reports for select to authenticated using (true);
create policy "authenticated can read files" on public.files for select to authenticated using (true);
create policy "authenticated can read kg_nodes" on public.kg_nodes for select to authenticated using (true);
create policy "authenticated can read kg_edges" on public.kg_edges for select to authenticated using (true);
create policy "authenticated can read chunks" on public.chunks for select to authenticated using (true);
create policy "authenticated can insert own rag logs" on public.rag_query_logs for insert to authenticated with check (auth.uid() = user_id);
create policy "authenticated can read own rag logs" on public.rag_query_logs for select to authenticated using (auth.uid() = user_id);

create or replace function public.search_chunks(
  query_text text,
  match_limit integer default 8,
  research_ids text[] default null
)
returns table (
  id bigint,
  document_id text,
  chunk_index integer,
  research_id text,
  title text,
  organ_name text,
  file_id text,
  file_name text,
  text text,
  score real,
  metadata jsonb
)
language sql
stable
as $$
  select
    c.id,
    c.document_id,
    c.chunk_index,
    c.research_id,
    c.title,
    c.organ_name,
    c.file_id,
    c.file_name,
    c.text,
    greatest(similarity(c.text, query_text), similarity(coalesce(c.title, ''), query_text))::real as score,
    c.metadata
  from public.chunks c
  where
    (research_ids is null or c.research_id = any(research_ids))
    and (
      c.text ilike '%' || query_text || '%'
      or c.title ilike '%' || query_text || '%'
      or similarity(c.text, query_text) > 0.08
    )
  order by score desc, c.id
  limit least(greatest(match_limit, 1), 50);
$$;

create or replace function public.kg_search(
  terms text[],
  kinds text[] default null,
  match_limit integer default 20
)
returns table (
  id text,
  kind text,
  label text,
  data jsonb,
  score real
)
language sql
stable
as $$
  select
    n.id,
    n.kind,
    n.label,
    n.data,
    max(greatest(similarity(n.label, term), case when n.label ilike '%' || term || '%' then 1 else 0 end))::real as score
  from public.kg_nodes n
  cross join unnest(terms) as term
  where
    term <> ''
    and (kinds is null or n.kind = any(kinds))
    and (n.label ilike '%' || term || '%' or similarity(n.label, term) > 0.12)
  group by n.id, n.kind, n.label, n.data
  order by score desc, n.kind, n.label
  limit least(greatest(match_limit, 1), 100);
$$;

create or replace function public.kg_summary(match_limit integer default 12)
returns jsonb
language sql
stable
as $$
  select jsonb_build_object(
    'node_kinds', coalesce((
      select jsonb_agg(jsonb_build_object('label', label, 'value', value) order by value desc, label)
      from (
        select coalesce(kind, 'unknown') as label, count(*) as value
        from public.kg_nodes
        group by coalesce(kind, 'unknown')
        order by value desc, label
        limit least(greatest(match_limit, 1), 50)
      ) s
    ), '[]'::jsonb),
    'edge_kinds', coalesce((
      select jsonb_agg(jsonb_build_object('label', label, 'value', value) order by value desc, label)
      from (
        select coalesce(kind, 'unknown') as label, count(*) as value
        from public.kg_edges
        group by coalesce(kind, 'unknown')
        order by value desc, label
        limit least(greatest(match_limit, 1), 50)
      ) s
    ), '[]'::jsonb),
    'top_connected_nodes', coalesce((
      select jsonb_agg(jsonb_build_object('id', id, 'kind', kind, 'label', label, 'degree', degree) order by degree desc, kind, label)
      from (
        select n.id, n.kind, n.label, count(e.id) as degree
        from public.kg_nodes n
        left join public.kg_edges e on e.from_id = n.id or e.to_id = n.id
        group by n.id, n.kind, n.label
        order by degree desc, n.kind, n.label
        limit least(greatest(match_limit, 1), 50)
      ) s
    ), '[]'::jsonb)
  );
$$;

create or replace function public.project_summary(match_limit integer default 12)
returns jsonb
language sql
stable
as $$
  select jsonb_build_object(
    'top_orgs', coalesce((
      select jsonb_agg(jsonb_build_object('label', label, 'value', value) order by value desc, label)
      from (
        select coalesce(nullif(organ_name, ''), '미분류') as label, count(*) as value
        from public.projects
        group by coalesce(nullif(organ_name, ''), '미분류')
        order by value desc, label
        limit least(greatest(match_limit, 1), 50)
      ) s
    ), '[]'::jsonb),
    'top_fields', coalesce((
      select jsonb_agg(jsonb_build_object('label', label, 'value', value) order by value desc, label)
      from (
        select coalesce(nullif(brm_biz_name, ''), nullif(biz_name, ''), '미분류') as label, count(*) as value
        from public.projects
        group by coalesce(nullif(brm_biz_name, ''), nullif(biz_name, ''), '미분류')
        order by value desc, label
        limit least(greatest(match_limit, 1), 50)
      ) s
    ), '[]'::jsonb),
    'years', coalesce((
      select jsonb_agg(jsonb_build_object('label', label, 'value', value) order by label desc)
      from (
        select coalesce(nullif(issued_year, ''), substr(research_start_date, 1, 4), '미상') as label, count(*) as value
        from public.projects
        group by coalesce(nullif(issued_year, ''), substr(research_start_date, 1, 4), '미상')
        order by label desc
        limit least(greatest(match_limit, 1), 50)
      ) s
    ), '[]'::jsonb),
    'file_status', coalesce((
      select jsonb_agg(jsonb_build_object('label', label, 'value', value) order by value desc, label)
      from (
        select coalesce(nullif(status, ''), 'pending') as label, count(*) as value
        from public.files
        group by coalesce(nullif(status, ''), 'pending')
        order by value desc, label
      ) s
    ), '[]'::jsonb)
  );
$$;

create or replace function public.operations_status()
returns jsonb
language sql
stable
as $$
  select jsonb_build_object(
    'projects', (select count(*) from public.projects),
    'files', (select count(*) from public.files),
    'downloaded_files', (select count(*) from public.files where status = 'downloaded'),
    'downloaded_waiting_conversion', (
      select count(*)
      from public.files f
      where f.status = 'downloaded'
        and not exists (select 1 from public.chunks c where c.file_id = f.id)
    ),
    'converted_files', (select count(*) from public.files where status = 'converted'),
    'convert_failed_files', (select count(*) from public.files where status = 'convert_failed'),
    'metadata_only_files', (select count(*) from public.files where status = 'metadata_only'),
    'chunks', (select count(*) from public.chunks),
    'kg_nodes', (select count(*) from public.kg_nodes),
    'kg_edges', (select count(*) from public.kg_edges),
    'api_calls_today', 0,
    'api_failures', 0,
    'recent_failures', '[]'::jsonb,
    'conversion_rate', round(((select count(*) from public.files where status = 'converted')::numeric / greatest((select count(*) from public.files), 1)) * 100, 2)
  );
$$;

grant execute on function public.search_chunks(text, integer, text[]) to authenticated, service_role;
grant execute on function public.kg_search(text[], text[], integer) to authenticated, service_role;
grant execute on function public.kg_summary(integer) to authenticated, service_role;
grant execute on function public.project_summary(integer) to authenticated, service_role;
grant execute on function public.operations_status() to authenticated, service_role;
