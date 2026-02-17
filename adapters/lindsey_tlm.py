import hashlib, json, uuid
from datetime import datetime, timezone
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from core.store_offchain import store_offchain
from core.sign_payload    import sign_payload

def normalize_tlm(raw: dict, asset_id: str = None, weather_cell: str = "WCELL-DEFAULT") -> dict:
    required = ["current_rms_amps","conductor_temp_celsius",
                "clearance_to_ground_m","load_percentage","device_serial"]
    missing = [f for f in required if f not in raw]
    if missing:
        raise ValueError(f"TLM missing: {missing}")
    canonical = {
        "event_id":               str(uuid.uuid4()),
        "source_product":         "TLM",
        "source_vendor":          "lindsey_systems",
        "asset_id":               asset_id or raw.get("line_segment_id","UNKNOWN"),
        "weather_cell_id":        weather_cell,
        "timestamp_utc":          raw.get("device_timestamp_utc",
                                  datetime.now(timezone.utc).isoformat()),
        "electrical": {
            "current_rms_amps":   raw["current_rms_amps"],
            "load_percentage":    raw["load_percentage"],
        },
        "mechanical": {
            "conductor_temp_celsius": raw["conductor_temp_celsius"],
            "clearance_to_ground_m":  raw["clearance_to_ground_m"],
            "sag_alert":              raw["clearance_to_ground_m"] < 5.5,
        },
        "device_health": {
            "battery_voltage_v":    raw.get("battery_voltage_v"),
            "battery_ok":           raw.get("battery_voltage_v", 99) > 3.6,
            "firmware_version":     raw.get("firmware_version"),
        },
        "identity": {
            "device_serial":    raw["device_serial"],
            "line_segment_id":  raw.get("line_segment_id"),
        }
    }
    payload_bytes = json.dumps(canonical, sort_keys=True, separators=(",",":")).encode()
    payload_hash  = "sha256:" + hashlib.sha256(payload_bytes).hexdigest()
    payload_uri   = store_offchain(payload_bytes, {"product":"TLM","asset":asset_id})
    attestation   = sign_payload(canonical)
    alerts = []
    if raw["load_percentage"] > 95:           alerts.append("LOAD_CRITICAL")
    if raw["clearance_to_ground_m"] < 5.0:   alerts.append("CLEARANCE_CRITICAL")
    if raw.get("battery_voltage_v", 99) < 3.6: alerts.append("BATTERY_LOW")
    return {
        "event_id":     canonical["event_id"],
        "payload_hash": payload_hash,
        "payload_uri":  payload_uri,
        "attestation":  attestation,
        "compliance":   {"nerc_cip":"CIP-007-6-R4","ferc_881":False,
                         "audit_ready":True,"alerts":alerts},
        "data":         canonical,
    }
