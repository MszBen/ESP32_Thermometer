-- Run once in the Supabase dashboard: SQL Editor -> New query -> paste -> Run.
-- Lets the board report problems (sensor failed, upload rejected, Wi-Fi was down)
-- so the website can show them.

create table if not exists device_errors (
  id bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  device_id text not null default 'esp32-c3-1',
  message text not null check (char_length(message) <= 200)
);

alter table device_errors enable row level security;

create policy "device can report errors" on device_errors
  for insert to anon with check (true);
create policy "website can read errors" on device_errors
  for select to anon using (true);
