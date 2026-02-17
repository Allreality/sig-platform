import hashlib, json, uuid
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.store_offchain import store_offchain
from core.sign_payload    import sign_payload

def normalize_smartline(raw: dict, asset_id: str = None, weather_cell: str = "WCELL-DEFAULT") -> dict:
    required = ["aar_amps","dlr_current_amps","emergency_rating_amps",
                "model_version","line_section_id"]
    missing = [f for f in required if f not in raw]
    if missing:
        raise ValueError(f"SMARTLINE missing: {missing}")
    canonical = {
        "event_id":        str(uuid.uuid4()),
        "source_product":  "SMARTLINE",
        "source_vendor":   "lindsey_systems",
        "asset_id":        asset_id or raw["line_section_id"],
        "weather_cell_id": weather_cell,
        "timestamp_utc":   raw.get("rating_timestamp_utc",
                           datetime.now(timezone.utc).isoformat()),
        "ratings": {
            "aar_amps":              raw["aar_amps"],
            "dlr_current_amps":      raw["dlr_current_amps"],
            "emergency_rating_amps": raw["emergency_rating_amps"],
            "transient_rating_amps": raw.get("transient_rating_amps"),
            "dlr_vs_aar_ratio":      round(raw["dlr_current_amps"]/raw["aar_amps"],4)
                                     if raw["aar_amps"] > 0 else None,
        },
        "forecast_curves":  raw.get("forecast_curves", []),
        "limiting_element": raw.get("limiting_element", {}),
        "model": {
            "version":          raw["model_version"],
            "last_updated":     raw.get("model_last_updated"),
            "weather_stations": raw.get("weather_station_ids", []),
        },
        "identity": {
            "line_section_id": raw["line_section_id"],
            "utility_id":      raw.get("utility_id"),
        }
    }
    payload_bytes = json.dumps(canonical, sort_keys=True, separators=(",",":")).encode()
    payload_hash  = "sha256:" + hashlib.sha256(payload_bytes).hexdigest()
    payload_uri   = store_offchain(payload_bytes, {"product":"SMARTLINE","ferc_881":True})
    attestation   = sign_payload(canonical)
    alerts = []
    if raw["dlr_current_amps"] < raw["aar_amps"] * 0.80:
        alerts.append("DLR_BELOW_AAR")
    forecasts = raw.get("forecast_curves", [])
    next_hr = [f for f in forecasts if f.get("horizon_minutes",99) <= 60]
    if next_hr and next_hr[-1]["rating_amps"] < raw["dlr_current_amps"] * 0.85:
        alerts.append("RATING_DECLINING")
    return {
        "event_id":     canonical["event_id"],
        "payload_hash": payload_hash,
        "payload_uri":  payload_uri,
        "attestation":  attestation,
        "compliance":   {"nerc_cip":"CIP-007-6-R4","ferc_881":True,
                         "ferc_881_submittable":True,"audit_ready":True,"alerts":alerts},
        "data":         canonical,
    }
