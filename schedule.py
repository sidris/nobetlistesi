-- Supabase SQL Editor'da bir kere çalıştırın.
-- Tüm uygulama durumunu (kişiler, görevler, kurallar, izinler, notlar, çizelge)
-- tek bir JSONB satırında tutar. Basit, tek paylaşımlı çizelge içindir.

create table if not exists public.nobet_state (
  id         text primary key,
  data       jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

-- updated_at otomatik güncellensin
create or replace function public.nobet_touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists nobet_touch on public.nobet_state;
create trigger nobet_touch before update on public.nobet_state
for each row execute function public.nobet_touch_updated_at();

-- Row Level Security: erişim uygulama üzerinden (anahtar Streamlit secrets'te,
-- sunucu tarafında) ve uygulama içi şifreyle denetlendiğinden, okuma/yazmaya izin veriyoruz.
alter table public.nobet_state enable row level security;

drop policy if exists nobet_read  on public.nobet_state;
drop policy if exists nobet_write on public.nobet_state;
drop policy if exists nobet_upd   on public.nobet_state;

create policy nobet_read  on public.nobet_state for select using (true);
create policy nobet_write on public.nobet_state for insert with check (true);
create policy nobet_upd   on public.nobet_state for update using (true) with check (true);

-- Başlangıç satırı (uygulama yoksa kendi de oluşturur)
insert into public.nobet_state (id, data)
values ('main', '{}'::jsonb)
on conflict (id) do nothing;
