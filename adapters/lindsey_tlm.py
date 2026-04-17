import uuid, hashlib, json
from datetime import datetime, timezone

def normalize_tlm(data: dict, asset_id: str = None, weather_cell: str = "WCELL-DEFAULT") -> dict:
    payload_str  = json.dumps(data, sort_keys=True)
    payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()
    return {
        "event_id":    str(uuid.uuid4()),
        "source":      "TLM",
        "asset_id":    asset_id,
        "weather_cell":weather_cell,
        "data":        data,
        "payload_hash":payload_hash,
        "payload_uri": f"sig://tlm/{payload_hash}",
        "ts":          datetime.now(timezone.utc).isoformat()
    }
