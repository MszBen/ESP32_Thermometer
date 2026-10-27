"""ESP32 Thermometer website: latest reading, history, on-demand readings and settings."""
import hmac
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE = Path(__file__).parent
LONDON = ZoneInfo("Europe/London")

# For local testing, read web/.env if it exists (on Vercel the real env vars are used).
env_file = BASE / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())

app = FastAPI()
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

# Editable on /settings: name -> (label, help text, type, minimum, maximum).
SETTING_FIELDS = {
    "check_interval_s": ("Check for button presses every (seconds)", "How often the board wakes to see if you pressed the button. Lower = faster response but more battery use.", int, 30, 3600),
    "reading_interval_min": ("Scheduled reading every (minutes)", "The regular reading that builds the history.", int, 1, 1440),
    "temp_offset": ("Temperature offset (°C)", "Added to every reading the board posts. Use 1 if it reads 1 °C too low. Old readings are not changed.", float, -20, 20),
    "humidity_offset": ("Humidity offset (%)", "Added to every humidity reading the board posts.", float, -50, 50),
    "sensor_retries": ("Sensor retries", "How many times the board tries the DHT11 before giving up.", int, 1, 10),
    "wifi_timeout_s": ("Wi-Fi timeout (seconds)", "How long the board waits to connect.", int, 5, 60),
    "history_hours": ("History shown (hours)", "How far back the chart and table go.", int, 1, 168),
}
# Used if the settings table can't be read. Same as the database defaults.
DEFAULT_SETTINGS = {
    "check_interval_s": 180, "reading_interval_min": 30, "temp_offset": 0, "humidity_offset": 0,
    "sensor_retries": 3, "wifi_timeout_s": 20, "history_hours": 24,
}


async def supabase(method: str, path: str, *, service: bool = False, params=None, json=None, prefer=None):
    """Call Supabase's REST API. service=True uses the server-side key (needed for writes)."""
    key = os.environ["SUPABASE_SERVICE_KEY" if service else "SUPABASE_ANON_KEY"]
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    if prefer:
        headers["Prefer"] = prefer
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.request(method, url, headers=headers, params=params, json=json)
        response.raise_for_status()
        return response.json() if response.content else None


async def get_settings() -> dict:
    try:
        rows = await supabase("GET", "settings", params={"id": "eq.1", "select": "*"})
        return {**DEFAULT_SETTINGS, **rows[0]} if rows else dict(DEFAULT_SETTINGS)
    except (httpx.HTTPError, KeyError):
        return dict(DEFAULT_SETTINGS)


def to_london(timestamp: str) -> datetime:
    """Supabase gives UTC like 2026-10-27T12:00:00.123+00:00; show it in UK time."""
    return datetime.fromisoformat(timestamp).astimezone(LONDON)


def format_latest(row: dict) -> dict:
    return {
        "temperature": row["temperature"],
        "humidity": row["humidity"],
        "time": to_london(row["created_at"]).strftime("%d %b %Y, %H:%M"),
    }


@app.get("/")
async def index(request: Request):
    settings = await get_settings()
    since = (datetime.now(timezone.utc) - timedelta(hours=settings["history_hours"])).isoformat()
    try:
        # Latest is a separate query so it still shows if the board has been offline a while.
        latest_rows = await supabase(
            "GET", "readings",
            params={"select": "created_at,temperature,humidity", "order": "created_at.desc", "limit": 1},
        )
        history_rows = await supabase(
            "GET", "readings",
            params={"select": "created_at,temperature,humidity", "created_at": f"gte.{since}", "order": "created_at.asc"},
        )
        error = None
    except (httpx.HTTPError, KeyError) as exc:
        latest_rows, history_rows, error = [], [], f"Could not load readings ({type(exc).__name__})."

    history = [
        {"time": to_london(r["created_at"]).strftime("%H:%M"), "temperature": r["temperature"], "humidity": r["humidity"]}
        for r in history_rows
    ]

    # Problems the board reported in the last 24 h (empty if the table isn't set up yet).
    try:
        error_rows = await supabase(
            "GET", "device_errors",
            params={
                "select": "created_at,message",
                "created_at": f"gte.{(datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()}",
                "order": "created_at.desc",
                "limit": 5,
            },
        )
    except (httpx.HTTPError, KeyError):
        error_rows = []
    board_errors = [
        {"time": to_london(r["created_at"]).strftime("%d %b, %H:%M"), "message": r["message"]} for r in error_rows
    ]

    # No reading for a long time usually means the board is off, out of Wi-Fi range or stuck.
    offline = None
    if latest_rows:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(latest_rows[0]["created_at"])
        if age > timedelta(minutes=settings["reading_interval_min"] * 2 + 5):
            hours, minutes = divmod(int(age.total_seconds() // 60), 60)
            offline = f"No reading for {hours} h {minutes} min, so the board may be offline."
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "latest": format_latest(latest_rows[0]) if latest_rows else None,
            "history": history,
            "error": error,
            "offline": offline,
            "board_errors": board_errors,
            "history_hours": settings["history_hours"],
            "check_interval_s": settings["check_interval_s"],
        },
    )


@app.post("/api/capture")
async def capture():
    """The button: ask the board for a reading. It picks the request up on its next check."""
    try:
        pending = await supabase("GET", "pending_requests", params={"select": "id", "order": "id.desc", "limit": 1})
        if pending:
            return {"request_id": pending[0]["id"]}   # already waiting, so don't pile up requests
        created = await supabase("POST", "capture_requests", service=True, json={}, prefer="return=representation")
        return {"request_id": created[0]["id"]}
    except (httpx.HTTPError, KeyError):
        return JSONResponse({"error": "Could not send the request."}, status_code=502)


@app.get("/api/capture/{request_id}")
async def capture_status(request_id: int):
    """Has the board answered this request yet? If so, return the reading it posted."""
    try:
        rows = await supabase(
            "GET", "readings",
            params={"select": "created_at,temperature,humidity", "request_id": f"gte.{request_id}", "order": "created_at.desc", "limit": 1},
        )
    except (httpx.HTTPError, KeyError):
        return JSONResponse({"error": "Could not check."}, status_code=502)
    return {"done": bool(rows), "reading": format_latest(rows[0]) if rows else None}


def settings_page(request: Request, settings: dict, message=None, error=None, status_code=200):
    return templates.TemplateResponse(
        request,
        "settings.html",
        {"fields": SETTING_FIELDS, "settings": settings, "message": message, "error": error},
        status_code=status_code,
    )


@app.get("/settings")
async def settings_form(request: Request):
    return settings_page(request, await get_settings())


@app.post("/settings")
async def settings_save(request: Request, password: str = Form("")):
    settings = await get_settings()
    expected = os.environ.get("ADMIN_PASSWORD", "")
    if not expected or not hmac.compare_digest(password.encode(), expected.encode()):
        return settings_page(request, settings, error="Wrong password.", status_code=403)

    form = await request.form()
    new = {}
    for name, (_, _, kind, low, high) in SETTING_FIELDS.items():
        try:
            value = kind(form.get(name, ""))
        except ValueError:
            return settings_page(request, {**settings, **dict(form)}, error=f"{name} must be a number.", status_code=400)
        if not low <= value <= high:
            return settings_page(request, {**settings, **dict(form)}, error=f"{name} must be between {low} and {high}.", status_code=400)
        new[name] = value
    try:
        await supabase("PATCH", "settings", service=True, params={"id": "eq.1"}, json=new)
    except (httpx.HTTPError, KeyError):
        return settings_page(request, {**settings, **new}, error="Could not save to Supabase.", status_code=502)
    return settings_page(request, {**settings, **new}, message="Saved. The board picks this up on its next check.")
