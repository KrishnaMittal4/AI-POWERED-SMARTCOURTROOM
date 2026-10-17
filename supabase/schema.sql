-- LEXAI production persistence schema (safe to run more than once)
create extension if not exists pgcrypto;

create table if not exists public.lexai_users (
  id uuid primary key default gen_random_uuid(),
  external_user_id text unique not null,
  name text,
  email text unique,
  password_hash text,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);
alter table public.lexai_users add column if not exists name text;
alter table public.lexai_users add column if not exists password_hash text;
create unique index if not exists lexai_users_email_unique on public.lexai_users(email) where email is not null;

create table if not exists public.cases (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.lexai_users(id) on delete cascade,
  title text not null, description text, status text default 'active', created_at timestamptz default now(), updated_at timestamptz default now()
);
create index if not exists idx_cases_user on public.cases(user_id);

create table if not exists public.documents (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.lexai_users(id) on delete cascade,
  case_id uuid not null references public.cases(id) on delete cascade, filename text not null, original_filename text,
  storage_path text not null, document_type text default 'OTHER', mime_type text, file_size bigint, file_hash text,
  page_count integer default 0, extraction_method text, ocr_pages integer default 0, ocr_quality double precision,
  processing_status text default 'pending', created_at timestamptz default now(), updated_at timestamptz default now()
);
create index if not exists idx_documents_case on public.documents(case_id);
create index if not exists idx_documents_user on public.documents(user_id);

create table if not exists public.document_chunks (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.lexai_users(id) on delete cascade,
  case_id uuid not null references public.cases(id) on delete cascade, document_id uuid not null references public.documents(id) on delete cascade,
  page_number integer, chunk_index integer, text text not null, case_role text default 'OTHER', role_confidence double precision,
  metadata jsonb default '{}'::jsonb, created_at timestamptz default now()
);
create index if not exists idx_chunks_case on public.document_chunks(case_id);
create index if not exists idx_chunks_document on public.document_chunks(document_id);

create table if not exists public.case_intelligence (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.lexai_users(id) on delete cascade,
  case_id uuid not null references public.cases(id) on delete cascade, summary jsonb default '{}'::jsonb,
  timeline jsonb default '[]'::jsonb, evidence jsonb default '[]'::jsonb, contradictions jsonb default '[]'::jsonb,
  legal_issues jsonb default '[]'::jsonb, document_fingerprint text, created_at timestamptz default now(), updated_at timestamptz default now(), unique(case_id)
);

create table if not exists public.legal_issues (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.lexai_users(id) on delete cascade,
  case_id uuid not null references public.cases(id) on delete cascade, title text not null, description text, issue_type text,
  evidence_strength text, metadata jsonb default '{}'::jsonb, created_at timestamptz default now(), updated_at timestamptz default now()
);
create index if not exists idx_legal_issues_case on public.legal_issues(case_id);

create table if not exists public.evidence_links (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.lexai_users(id) on delete cascade,
  case_id uuid not null references public.cases(id) on delete cascade, issue_id uuid references public.legal_issues(id) on delete cascade,
  document_id uuid references public.documents(id) on delete cascade, page_number integer, evidence_type text, relation text,
  excerpt text, strength double precision, metadata jsonb default '{}'::jsonb, created_at timestamptz default now()
);
create index if not exists idx_evidence_case on public.evidence_links(case_id);

create table if not exists public.contradictions (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.lexai_users(id) on delete cascade,
  case_id uuid not null references public.cases(id) on delete cascade, contradiction_type text, statement_a text, statement_b text,
  source_a_document uuid references public.documents(id) on delete set null, source_a_page integer,
  source_b_document uuid references public.documents(id) on delete set null, source_b_page integer, severity text,
  metadata jsonb default '{}'::jsonb, created_at timestamptz default now()
);
create index if not exists idx_contradictions_case on public.contradictions(case_id);

create table if not exists public.moot_sessions (
  id uuid primary key default gen_random_uuid(), user_id uuid not null references public.lexai_users(id) on delete cascade,
  case_id uuid references public.cases(id) on delete cascade, title text, conversation jsonb default '[]'::jsonb,
  session_metadata jsonb default '{}'::jsonb, created_at timestamptz default now(), updated_at timestamptz default now()
);

-- Generic persisted cache for expensive derived analysis. Never stores the 848-judgment research corpus.
create table if not exists public.case_runtime_cache (
  user_id uuid not null references public.lexai_users(id) on delete cascade,
  case_id uuid not null references public.cases(id) on delete cascade,
  kind text not null, fingerprint text not null, payload jsonb not null default '{}'::jsonb,
  updated_at timestamptz default now(), primary key(user_id,case_id,kind)
);

-- Backend-only architecture: deny anonymous/authenticated direct table access.
alter table public.lexai_users enable row level security;
alter table public.cases enable row level security;
alter table public.documents enable row level security;
alter table public.document_chunks enable row level security;
alter table public.case_intelligence enable row level security;
alter table public.legal_issues enable row level security;
alter table public.evidence_links enable row level security;
alter table public.contradictions enable row level security;
alter table public.moot_sessions enable row level security;
alter table public.case_runtime_cache enable row level security;
-- No client policies are created. LEXAI's backend secret/service role bypasses RLS after its own JWT ownership checks.

-- Feedback-learning events. These rewards tune retrieval only within strict
-- bounds; they never change citation/evidence verification outcomes.
create table if not exists public.rag_feedback (
  id bigint generated by default as identity primary key,
  created_at timestamptz default now(),
  question text not null,
  answer text not null default '',
  sources jsonb not null default '[]'::jsonb,
  rating integer not null check (rating between -1 and 1),
  comment text,
  top_score double precision,
  weak_match boolean default false,
  not_found boolean default false,
  query_type text default 'mixed',
  reward double precision default 0,
  correct_source text,
  event_type text default 'answer_rating'
);
create index if not exists idx_rag_feedback_qtype on public.rag_feedback(query_type);
create index if not exists idx_rag_feedback_source on public.rag_feedback(correct_source);
alter table public.rag_feedback enable row level security;
