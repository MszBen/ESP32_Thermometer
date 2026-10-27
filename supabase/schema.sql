create table readings (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  device_id text not null default 'esp32-c3-1',
  temperature real not null,
  humidity real not null
);

alter table readings enable row level security;

create policy "device can insert" on readings
  for insert to anon with check (true);

create policy "website can read" on readings
  for select to anon using (true);

-- On-demand readings and editable settings: see migration_capture_settings.sql
-- (run it after this file; it also adds readings.request_id).
