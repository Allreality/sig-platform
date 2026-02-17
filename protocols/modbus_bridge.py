import os, time, requests
from datetime import datetime, timezone

INGEST_URL    = os.getenv("INGEST_URL",   "http://localhost:5010/ingest")
MODBUS_HOSTS  = os.getenv("MODBUS_HOSTS", "").split(",")
POLL_SECONDS  = int(os.getenv("POLL_SECONDS", 60))

def poll_modbus(host: str) -> dict:
    return {
        "current_rms_amps":       485.2,
        "conductor_temp_celsius": 52.3,
        "clearance_to_ground_m":  8.7,
        "load_percentage":        40.4,
        "battery_voltage_v":      3.85,
        "device_serial":          f"MODBUS-{host.replace('.', '-')}",
        "line_segment_id":        f"LINE-{host.replace('.', '-')}",
        "device_timestamp_utc":   datetime.now(timezone.utc).isoformat(),
    }

def run():
    print(f"[Modbus] Polling {len(MODBUS_HOSTS)} hosts every {POLL_SECONDS}s")
    while True:
        for host in MODBUS_HOSTS:
            if not host.strip(): continue
            try:
                raw = poll_modbus(host.strip())
                r = requests.post(INGEST_URL, json={"product":"MODBUS_AUTO","data":raw}, timeout=15)
                print(f"[Modbus] {host} → {r.json().get('event_id','error')}")
            except Exception as e:
                print(f"[Modbus] {host} ERROR: {e}")
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    run()
