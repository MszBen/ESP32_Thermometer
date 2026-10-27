# ESP32 Thermometer

An ESP32-C3 reads temperature and humidity from a DHT11 and posts the readings to
Supabase. A website hosted on Vercel displays them, and has a button to ask the board for a
reading right now.

```
ESP32-C3 (MicroPython) <-> Supabase (REST) <-> Python website (FastAPI) on Vercel
```

## Layout

| Folder | Contents |
| --- | --- |
| `firmware/` | MicroPython code for the board (`main.py`, `secrets.example.py`) |
| `firmware/tools/` | Small hardware test scripts used while wiring up the sensor |
| `supabase/` | SQL for the `readings` table, settings and button requests |
| `web/` | FastAPI + Jinja2 + Tailwind site; set Vercel's Root Directory to `web` |

## Wiring

DHT11 `+` to 3V3, `-` to GND, `out` to GPIO4.

## Database

In the Supabase SQL editor, run `supabase/schema.sql`, then `supabase/migration_capture_settings.sql`.

## Firmware setup

1. Flash MicroPython (`ESP32_GENERIC_C3`) with `esptool` at offset `0x0`.
2. Copy `firmware/secrets.example.py` to `firmware/secrets.py` and fill in your values.
3. Copy the files to the board (replace `COM3` with your port):
   ```
   cd firmware
   mpremote connect COM3 cp secrets.py :secrets.py
   mpremote connect COM3 run main.py
   ```
4. Once rows appear in Supabase, set `DEV = False` in `main.py` and copy it as `:main.py`.

The board wakes every few minutes (default 3) to look for a button press. It takes a scheduled
reading every 30 minutes. Both intervals, plus temperature and humidity offsets, are edited on the
website's `/settings` page.

## Website

```
cd web
py -3.13 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      # then fill in the values
python -m uvicorn main:app --reload
```

Environment variables (in `web/.env` locally, in Vercel's settings when deployed):
`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY` (server-side only) and `ADMIN_PASSWORD`.

Styling uses the [Tailwind standalone CLI](https://github.com/tailwindlabs/tailwindcss/releases)
(download `tailwindcss-windows-x64.exe` into `web/` as `tailwindcss.exe`). After changing templates:

```
.\tailwindcss.exe -i input.css -o static/styles.css --minify
```

`static/styles.css` is committed so Vercel doesn't need to build it.

## License

MIT, see [LICENSE](LICENSE).
