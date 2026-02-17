import requests, json, hashlib, sys

URL = "http://localhost:5010"

def check(label, condition, detail=""):
    if condition:
        print(f"  ✅ {label}")
    else:
        print(f"  ❌ {label} {detail}")
        sys.exit(1)

def test_health():
    print("\n[1] Health check")
    r = requests.get(f"{URL}/health", timeout=5)
    check("Server responding", r.status_code == 200)
    check("Status ok", r.json()["status"] == "ok")

def test_tlm_normal():
    print("\n[2] TLM - normal conditions")
    r = requests.post(f"{URL}/ingest", json={"product":"TLM","data":{
        "current_rms_amps":485.2,"conductor_temp_celsius":52.3,
        "clearance_to_ground_m":8.7,"load_percentage":40.4,
        "battery_voltage_v":3.85,"device_serial":"TEST-001",
        "line_segment_id":"LINE-001",
        "device_timestamp_utc":"2026-02-17T14:22:30Z"}}, timeout=15)
    d = r.json()
    check("Status 200",       r.status_code == 200)
    check("Has event_id",     "event_id"     in d)
    check("Has payload_hash", "payload_hash" in d)
    check("Hash is sha256",   d["payload_hash"].startswith("sha256:"))
    check("Has payload_uri",  "payload_uri"  in d)
    check("Audit ready",      d.get("audit_ready") == True)

def test_tlm_alerts():
    print("\n[3] TLM - critical alert conditions")
    r = requests.post(f"{URL}/ingest", json={"product":"TLM","data":{
        "current_rms_amps":1180.0,"conductor_temp_celsius":89.1,
        "clearance_to_ground_m":4.2,"load_percentage":98.3,
        "battery_voltage_v":3.4,"device_serial":"TEST-001",
        "line_segment_id":"LINE-001",
        "device_timestamp_utc":"2026-02-17T14:22:30Z"}}, timeout=15)
    check("Ingested ok", r.status_code == 200)
    check("Has event_id", "event_id" in r.json())

def test_smartline():
    print("\n[4] SMARTLINE - DLR ratings")
    r = requests.post(f"{URL}/ingest", json={"product":"SMARTLINE","data":{
        "aar_amps":1050.0,"dlr_current_amps":1180.0,
        "emergency_rating_amps":1350.0,"transient_rating_amps":1450.0,
        "forecast_curves":[
            {"horizon_minutes":15,"rating_amps":1175.0,"confidence":0.95},
            {"horizon_minutes":60,"rating_amps":1140.0,"confidence":0.88}],
        "limiting_element":{"element_type":"conductor","constraint_reason":"temperature"},
        "model_version":"2.1.4","rating_timestamp_utc":"2026-02-17T14:00:00Z",
        "line_section_id":"LINE-001","utility_id":"UTILITY-NE-042"}}, timeout=15)
    check("Ingested ok",  r.status_code == 200)
    check("Has event_id", "event_id" in r.json())

def run():
    print("=" * 45)
    print(" SIG Integration Test Suite")
    print(" Target: http://localhost:5010")
    print("=" * 45)
    try:
        test_health()
        test_tlm_normal()
        test_tlm_alerts()
        test_smartline()
        print("\n" + "=" * 45)
        print(" ALL TESTS PASSED")
        print(" Ready to contact Lindsey Systems.")
        print("=" * 45 + "\n")
    except SystemExit:
        print("\nFix failures before outreach.\n")
    except requests.exceptions.ConnectionError:
        print("\n❌ Cannot reach server. Run: docker-compose up -d\n")

if __name__ == "__main__":
    run()
