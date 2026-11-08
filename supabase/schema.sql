-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
--
-- Supabase holds ONLY what must outlive the EC2 server or follow a user across
-- devices: logins and saved results. The working data (graph, transactions) lives
-- in SQLite on the server. Never store names, account numbers, raw merchant
-- names or Nessie IDs here: aliases (acct_A) and percentages only.

-- One profile row per Supabase Auth user.
create table if not exists public.profiles (
  id           uuid primary key references auth.users (id) on delete cascade,
  display_name text,
  created_at   timestamptz not null default now()
);

-- A saved "what if" (e.g. buy a car) and its forecast summary.
create table if not exists public.saved_scenarios (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users (id) on delete cascade,
  name       text not null,
  params     jsonb not null,   -- scenario settings: {"price": 24000, "apr": 6.5, "months": 48}
  result     jsonb,            -- summary only: percentiles, overdraft probability, pillar scores
  created_at timestamptz not null default now()
);

-- History of accepted suggestions (the rule, not the Nessie record IDs).
create table if not exists public.accepted_rules (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references auth.users (id) on delete cascade,
  rule       jsonb not null,   -- {"kind":"savings_transfer","from":"acct_A","to":"acct_B","percent":5}
  status     text not null default 'active' check (status in ('active', 'undone')),
  created_at timestamptz not null default now(),
  undone_at  timestamptz
);

create index if not exists saved_scenarios_user_idx on public.saved_scenarios (user_id, created_at desc);
create index if not exists accepted_rules_user_idx  on public.accepted_rules  (user_id, created_at desc);

-- Row Level Security: a signed-in user (anon key + login) only sees their own rows.
-- The backend's service-role key bypasses RLS, so keep that key on the server.
alter table public.profiles        enable row level security;
alter table public.saved_scenarios enable row level security;
alter table public.accepted_rules  enable row level security;

create policy "own profile"   on public.profiles
  for all using (auth.uid() = id)      with check (auth.uid() = id);
create policy "own scenarios" on public.saved_scenarios
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own rules"     on public.accepted_rules
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

-- Create a profile automatically when someone signs up.
create or replace function public.handle_new_user() returns trigger
language plpgsql security definer set search_path = public as $$
begin
  insert into public.profiles (id) values (new.id) on conflict do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();
