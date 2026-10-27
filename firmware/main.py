import network, time, machine, dht
try:
    import requests
except ImportError:
    import urequests as requests
from secrets import *

DEV = False  # True: loop with prints (for testing). False: deep sleep between checks.

# Used if the settings can't be fetched. The real values are edited on the website.
DEFAULTS = {
    "check_interval_s": 180,
    "reading_interval_min": 30,
    "temp_offset": 0,
    "humidity_offset": 0,
    "sensor_retries": 3,
    "wifi_timeout_s": 20,
}

sensor = dht.DHT11(machine.Pin(4))
rtc = machine.RTC()
HEADERS = {"apikey": SUPABASE_KEY}

def connect_wifi(timeout):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        wlan.connect(WIFI_SSID, WIFI_PASSWORD)
        for _ in range(timeout):
            if wlan.isconnected():
                break
            time.sleep(1)
    return wlan.isconnected()

def read_sensor(retries):
    for _ in range(retries):
        try:
            sensor.measure()
            return sensor.temperature(), sensor.humidity()
        except OSError:
            time.sleep(2)
    return None

def sb_get(path):
    r = requests.get(SUPABASE_URL + "/rest/v1/" + path, headers=HEADERS)
    try:
        return r.json()
    finally:
        r.close()

def get_settings():
    settings = dict(DEFAULTS)
    try:
        rows = sb_get("settings?id=eq.1&select=*")
        if rows:
            settings.update(rows[0])
    except Exception as e:
        print("settings fetch failed, using defaults:", e)
    return settings

def get_pending_request():
    """Newest button press the board hasn't answered yet, or None."""
    try:
        rows = sb_get("pending_requests?select=id&order=id.desc&limit=1")
        return rows[0]["id"] if rows else None
    except Exception as e:
        print("request check failed:", e)
        return None

def post_reading(t, h, request_id):
    body = {"temperature": t, "humidity": h}
    if request_id:
        body["request_id"] = request_id
    r = requests.post(
        SUPABASE_URL + "/rest/v1/readings",
        json=body,
        headers={"apikey": SUPABASE_KEY, "Prefer": "return=minimal"},
    )
    print("POST status:", r.status_code)
    ok = r.status_code == 201
    r.close()
    return ok

def post_error(message):
    """Tell the website something went wrong. Returns True if it was saved."""
    try:
        r = requests.post(
            SUPABASE_URL + "/rest/v1/device_errors",
            json={"message": message[:200]},
            headers={"apikey": SUPABASE_KEY, "Prefer": "return=minimal"},
        )
        ok = r.status_code == 201
        r.close()
        return ok
    except Exception as e:
        print("could not report error:", e)
        return False

# State kept in RTC memory so it survives deep sleep, stored as "seconds|error":
#   seconds = time since the last scheduled reading (empty on first boot = take one straight away)
#   error   = a problem that couldn't be reported yet (e.g. Wi-Fi was down), sent on the next wake
def load_state():
    try:
        if machine.reset_cause() == machine.DEEPSLEEP_RESET:
            seconds, _, error = rtc.memory().decode().partition("|")
            return (int(seconds) if seconds else None), error
    except Exception:
        pass
    return None, ""

def save_state(elapsed, error):
    try:
        rtc.memory(((str(int(elapsed)) if elapsed is not None else "") + "|" + error[:200]).encode())
    except Exception:
        pass

def check_once(elapsed, queued_error):
    """One wake-up. Returns (elapsed, queued_error, sleep_s)."""
    if not connect_wifi(DEFAULTS["wifi_timeout_s"]):
        print("wifi failed")
        # Can't reach the server, so remember it and report on the next wake.
        error = queued_error or "Wi-Fi connection failed"
        wait = DEFAULTS["check_interval_s"]
        return (None if elapsed is None else elapsed + wait), error, wait

    errors = [queued_error] if queued_error else []
    settings = get_settings()
    sleep_s = max(30, int(settings["check_interval_s"]))   # never hammer the server
    request_id = get_pending_request()
    due = elapsed is None or elapsed >= settings["reading_interval_min"] * 60
    if request_id or due:
        reading = read_sensor(int(settings["sensor_retries"]))
        if not reading:
            print("sensor read failed")
            errors.append("Sensor read failed (check the DHT11 wiring)")
        else:
            t = round(reading[0] + settings["temp_offset"], 1)
            h = round(reading[1] + settings["humidity_offset"], 1)
            print("Temp:", t, "Humidity:", h, "request:", request_id)
            try:
                if post_reading(t, h, request_id):
                    if due:
                        elapsed = 0
                else:
                    errors.append("Upload to Supabase was rejected")
            except Exception as e:
                print("upload failed:", e)
                errors.append("Upload to Supabase failed: " + str(e))
    else:
        print("nothing to do")
    if due and elapsed != 0:
        elapsed = settings["reading_interval_min"] * 60   # reading failed: stay due, retry next wake

    # Report problems. Anything that can't be sent now is kept for the next wake.
    queued_error = ""
    for message in errors:
        if not post_error(message):
            queued_error = message
    return elapsed + sleep_s, queued_error, sleep_s

elapsed, queued_error = load_state()
if DEV:
    while True:
        elapsed, queued_error, sleep_s = check_once(elapsed, queued_error)
        time.sleep(sleep_s)
else:
    elapsed, queued_error, sleep_s = check_once(elapsed, queued_error)
    save_state(elapsed, queued_error)
    machine.deepsleep(sleep_s * 1000)
