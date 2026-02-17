import os, time, requests
from datetime import datetime, timezone

INGEST_URL   = os.getenv("INGEST_URL", "http://localhost:5010/ingest")
TLM_HOSTS    = os.getenv("TLM_HOSTS", "").split(",")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", 60))

def poll_tlm_device(host: str) -> dict:
    return {
        "current_rms_amps":         485.2,
        "conductor_temp_celsius":   52.3,
        "clearance_to_ground_m":    8.7,
        "load_percentage":          40.4,
        "battery_voltage_v":        3.85,
        "device_serial":            f"TLM-{host.replace('.', '-')}",
        "line_segment_id":          f"LINE-{host.replace('.', '-')}",
        "device_timestamp_utc":     datetime.now(timezone.utc).isoformat(),
    }

def run():
    print(f"[DNP3] Polling {len(TLM_HOSTS)} hosts every {POLL_SECONDS}s")
    while True:
        for host in TLM_HOSTS:
            if not host.strip(): continue
            try:
                raw = poll_tlm_device(host.strip())
                r = requests.post(INGEST_URL, json={"product":"DNP3_AUTO","data":raw}, timeout=15)
                print(f"[DNP3] {host} → {r.json().get('event_id','error')}")
            except Exception as e:
                print(f"[DNP3] {host} ERROR: {e}")
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    run()
