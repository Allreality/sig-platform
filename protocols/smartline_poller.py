import os, time, requests
from datetime import datetime, timezone

INGEST_URL       = os.getenv("INGEST_URL",       "http://localhost:5010/ingest")
SMARTLINE_URL    = os.getenv("SMARTLINE_API_URL", "")
SMARTLINE_KEY    = os.getenv("SMARTLINE_API_KEY", "")
LINE_SECTIONS    = os.getenv("LINE_SECTIONS",     "").split(",")
POLL_SECONDS     = int(os.getenv("POLL_SECONDS",  300))

def fetch_ratings(section_id: str) -> dict:
    if not SMARTLINE_URL:
        return {
            "aar_amps": 1050.0, "dlr_current_amps": 1180.0,
            "emergency_rating_amps": 1350.0, "transient_rating_amps": 1450.0,
            "forecast_curves": [
                {"horizon_minutes":15,  "rating_amps":1175.0, "confidence":0.95},
                {"horizon_minutes":60,  "rating_amps":1140.0, "confidence":0.88},
            ],
            "limiting_element": {"element_type":"conductor","constraint_reason":"temperature"},
            "model_version": "2.1.4", "rating_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "line_section_id": section_id, "utility_id": "UTILITY-DEFAULT",
        }
    r = requests.get(f"{SMARTLINE_URL}/api/v1/ratings/{section_id}/current",
        headers={"Authorization": f"Bearer {SMARTLINE_KEY}"}, timeout=30)
    r.raise_for_status()
    return r.json()

def run():
    print(f"[SMARTLINE] Polling {len(LINE_SECTIONS)} sections every {POLL_SECONDS}s")
    while True:
        for section in LINE_SECTIONS:
            if not section.strip(): continue
            try:
                raw = fetch_ratings(section.strip())
                r = requests.post(INGEST_URL, json={"product":"SMARTLINE","data":raw}, timeout=15)
                print(f"[SMARTLINE] {section} → {r.json().get('event_id','error')}")
            except Exception as e:
                print(f"[SMARTLINE] {section} ERROR: {e}")
        time.sleep(POLL_SECONDS)

if __name__ == "__main__":
    run()
