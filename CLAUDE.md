# ESP32 Thermometer

## What this is

An ESP32-C3 reads temperature and humidity from a DHT11 every 30 minutes and posts the
readings to Supabase over HTTPS. A website hosted on Vercel shows the latest reading and history.

```
ESP32-C3 (MicroPython) -> Supabase REST API -> Python website on Vercel
```

The owner (Ben) prefers Python everywhere and is a hobbyist: explain non-obvious steps briefly,
and keep things simple.

## Repo layout

| Path | Contents |
| --- | --- |
| `firmware/main.py` | Board code: read DHT11, connect Wi-Fi, POST to Supabase, then deep sleep |
| `firmware/secrets.example.py` | Template for `secrets.py` (Wi-Fi + Supabase URL/key). Real `secrets.py` is git-ignored |
| `firmware/tools/` | Small hardware diagnostic scripts (DHT probe, pin-level checks) |
| `supabase/schema.sql` | `readings` table plus row level security policies |
| `supabase/migration_capture_settings.sql` | Run after `schema.sql`: `settings`, `capture_requests`, `pending_requests` view, `readings.request_id` |
| `web/` | The website (FastAPI + Jinja2 + Tailwind). `main.py` is the Vercel entrypoint |

## Hardware

- Board: ESP32-C3 core board, running MicroPython `ESP32_GENERIC_C3` (flashed at offset `0x0`).
- Sensor: DHT11 on a 3-pin module (`+`, `out`, `-`), wired `+` to 3V3, `-` to GND, `out` to **GPIO4**.
  It reports whole degrees and whole % humidity only, and needs >= 2 s between reads.
  An occasional `ETIMEDOUT` is normal, so the code retries.
- Also owned but unused: a DS1307 RTC module (7-pin, coin cell). Not needed because Supabase
  timestamps rows with `created_at`.
- Ben is on **Windows 11 + PowerShell**. The board is on `COM3` (check Device Manager if it changes).

## Firmware workflow

Run these from `firmware/` with the venv active (`mpremote` and `esptool` are installed there):

```powershell
mpremote connect COM3 run main.py                 # run from PC, output prints in terminal
mpremote connect COM3 cp secrets.py :secrets.py   # REQUIRED once, and after any change
mpremote connect COM3 cp main.py :main.py         # make it run on power-up
mpremote connect COM3 ls                          # see what is on the board
```

Things that have already caused problems:

- **`secrets.py` must be copied to the board.** `mpremote run` only sends the script being run, so
  `from secrets import *` fails with "no module named secrets" until the file is on the board's own storage.
- **`main.py` has `DEV = False`** (real deep-sleep mode), and that version is on the board. Set `DEV = True`
  for testing (loops with prints, no deep sleep). While the board deep sleeps, the USB serial port disappears;
  hold BOOT and tap RESET to reprogram it.
- **No venv in this repo's `firmware/`.** `mpremote` and `esptool` live in the old folder's venv:
  `C:\Users\Ben\Documents\Python Projects\ESP32 Thermometer\venv\Scripts\`.
- **Board behaviour:** each wake it connects to Wi-Fi, reads `settings` and `pending_requests` from Supabase,
  takes a reading if a button press is pending or a scheduled reading is due, adds the temperature/humidity
  offsets, posts it (with `request_id` if it answers a button press), then sleeps `check_interval_s`
  (default 180 s, minimum 30). Time since the last scheduled reading is kept in RTC memory across deep sleep.
  Deep-sleep mode was started on the board (first reading posted), but a full wake cycle has not been observed yet.
- **`mpremote run` holds COM3** until it exits. Stop it before running another mpremote command.
- **Wiring faults look like code faults.** Loose breadboard legs gave `OSError: [Errno 116] ETIMEDOUT`.
  Diagnose with `firmware/tools/pin_pulldown.py`: it should print `1` (the module's pull-up is
  reaching the pin). `0` means `out` or `+` isn't connected.
- **Never move jumper wires while USB is plugged in.** A slip shorted the supply and dropped the USB
  connection (`SerialException: ClearCommError failed`).
- esptool needs `PyYAML`, which has no prebuilt wheel for the newest Python. If `pip install`
  tries to compile it, create the venv with Python 3.13 (`py -3.13 -m venv venv`).
- If PowerShell blocks `activate`: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`.

## Database (Supabase)

Run `supabase/schema.sql`, then `supabase/migration_capture_settings.sql`, in the Supabase SQL editor.

- `readings`: `id`, `created_at` (server default `now()`), `device_id` (default `esp32-c3-1`),
  `temperature` (real), `humidity` (real), `request_id` (set when the reading answers a button press).
  The board posts to `SUPABASE_URL/rest/v1/readings` with the `apikey` header and expects HTTP 201.
- `settings`: one row (`id = 1`) with `check_interval_s`, `reading_interval_min`, `temp_offset`,
  `humidity_offset`, `sensor_retries`, `wifi_timeout_s`, `history_hours`. Edited on the website's `/settings`.
  Offsets are applied by the board before posting, so old readings are not changed.
- `capture_requests`: one row per button press. The view `pending_requests` lists requests newer than the
  highest `request_id` in `readings`, so one reading answers every earlier press.
- Row level security is on. `anon` (the board, and the website's reads) can select from everything and insert
  readings. Only the website, using the server-side service key, can write `settings` and `capture_requests`.

Known trade-off: anyone with the anon key can insert readings. Fine for a hobby project. If it needs
locking down later, have the board POST to a token-protected route on the website and let the server
insert using a server-side key.

## Website (`web/`)

FastAPI + Jinja2 + Tailwind (standalone CLI, no Node). `main.py` is the entrypoint; Vercel finds the `app`
instance and `requirements.txt` there, with the project's **Root Directory set to `web`**.

- Pages: `/` (latest reading, chart and table for `history_hours`, "Take reading now" button) and
  `/settings` (password-protected form). API: `POST /api/capture`, `GET /api/capture/{id}`.
- The button inserts a `capture_requests` row; the page polls until the board posts a reading with that
  `request_id`, then reloads. The board only notices on its next check, so expect up to `check_interval_s`.
- Env vars (`web/.env` locally, Vercel settings when deployed, never in the repo): `SUPABASE_URL`,
  `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` (server-side only), `ADMIN_PASSWORD`. `web/.env.example` is the
  placeholder template and must never hold real values.
- Colours come from the `@theme` block in `web/input.css` (matches Ben's other site). After changing templates
  or `input.css`, rebuild: `.	ailwindcss.exe -i input.css -o static/styles.css --minify` from `web/`.
  `static/styles.css` is committed; `tailwindcss.exe` (about 112 MB) and `venv/` are git-ignored.
- Local run: from `web/`, `python -m uvicorn main:app --reload`. `.claude/launch.json` defines the preview server.
- Not deployed to Vercel yet.

## Repo conventions

- Never commit `firmware/secrets.py`, `.env` files, the `venv`, or `*.bin` firmware images (all in `.gitignore`).
  Run `git status` before every commit to check.
- If a secret is ever committed, rotate it. Deleting it later does not remove it from git history.
- License: MIT (`LICENSE`). Default branch: `main`.
- Do not delete or rewrite Ben's files on his PC without asking; the original working folder is
  `C:\Users\Ben\Documents\Python Projects\ESP32 Thermometer` and may still hold copies.

## Stale items to tidy

- Confirm the board wakes from deep sleep and keeps posting (a button press answered, a scheduled reading every 30 min).
- The board is USB-powered only; no battery holder yet (the 7-pin DS1307 module is a clock, not a power source).
