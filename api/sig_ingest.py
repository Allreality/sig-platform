import json, os, psycopg2
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Optional
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from adapters.lindsey_tlm       import normalize_tlm
from adapters.lindsey_smartline import normalize_smartline

app = FastAPI(title="SIG Ingest API", version="1.0")

class Payload(BaseModel):
    product:      str
    data:         dict[str, Any]
    asset_id:     Optional[str] = None
    weather_cell: Optional[str] = "WCELL-DEFAULT"

@app.post("/ingest")
async def ingest(p: Payload):
    try:
        if p.product in ("TLM","DNP3_AUTO","MODBUS_AUTO"):
            event = normalize_tlm(p.data, p.asset_id, p.weather_cell)
        elif p.product in ("SMARTLINE","SMARTLINE_TCF"):
            event = normalize_smartline(p.data, p.asset_id, p.weather_cell)
        else:
            raise ValueError(f"Unknown product: {p.product}")
        _write_ledger(event)
        return {"status":"ok","event_id":event["event_id"],
                "payload_hash":event["payload_hash"],
                "payload_uri":event["payload_uri"],"audit_ready":True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    from datetime import datetime, timezone
    return {"status":"ok","service":"sig-ingest",
            "time":datetime.now(timezone.utc).isoformat()}

def _write_ledger(event: dict):
    url = os.getenv("DATABASE_URL")
    if not url: return
    conn = psycopg2.connect(url)
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sig_events (
            event_id    TEXT PRIMARY KEY,
            payload_hash TEXT,
            payload_uri  TEXT,
            attestation  JSONB,
            compliance   JSONB,
            data         JSONB,
            created_at   TIMESTAMPTZ DEFAULT NOW()
        )""")
    cur.execute("""
        INSERT INTO sig_events (event_id,payload_hash,payload_uri,attestation,compliance,data)
        VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (event_id) DO NOTHING""",
        (event["event_id"], event["payload_hash"], event["payload_uri"],
         json.dumps(event["attestation"]), json.dumps(event["compliance"]),
         json.dumps(event["data"])))
    conn.commit(); cur.close(); conn.close()
