-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- Adds on-demand readings (the website's "Take reading now" button) and editable settings.
-- Writes to settings and capture_requests come only from the website using the service key,
-- which bypasses row level security. The anon key (the board) can only read them.

alter table readings add column if not exists request_id bigint;

create table if not exists settings (
  id int primary key default 1 check (id = 1),   -- always exactly one row
  check_interval_s int not null default 180,     -- how often the board checks for a button press
  reading_interval_min int not null default 30,  -- how often the board takes a scheduled reading
  temp_offset real not null default 0,           -- added to every temperature the board posts (degC)
  humidity_offset real not null default 0,       -- added to every humidity the board posts (%)
  sensor_retries int not null default 3,         -- DHT11 attempts before giving up
  wifi_timeout_s int not null default 20,        -- seconds to wait for Wi-Fi
  history_hours int not null default 24          -- hours shown on the website chart
);
insert into settings (id) values (1) on conflict do nothing;

create table if not exists capture_requests (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now()
);

alter table settings enable row level security;
alter table capture_requests enable row level security;

create policy "anyone can read settings" on settings
  for select to anon using (true);
create policy "anyone can read capture requests" on capture_requests
  for select to anon using (true);

-- A request is pending until a reading has been posted with a request_id at or above it.
create or replace view pending_requests with (security_invoker = true) as
  select id, created_at from capture_requests
  where id > coalesce((select max(request_id) from readings), 0);

grant select on pending_requests to anon;
