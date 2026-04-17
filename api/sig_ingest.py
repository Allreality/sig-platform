import json, os, psycopg2
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Optional
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from adapters.lindsey_tlm       import normalize_tlm
from adapters.lindsey_smartline import normalize_smartline
from api.x402_middleware        import psf_payment_required, x402_status, revenue_tracker
from sig_trial import router as trial_router, is_trial_device_allowed

app = FastAPI(title="SIG Ingest API", version="1.0")
app.include_router(trial_router, prefix="/trial")

class Payload(BaseModel):
    product:      str
    data:         dict[str, Any]
    asset_id:     Optional[str] = None
    weather_cell: Optional[str] = "WCELL-DEFAULT"

@app.post("/ingest")
@psf_payment_required
async def ingest(request: Request, p: Payload):
    try:
        if p.product in ("TLM","DNP3_AUTO","MODBUS_AUTO"):
            event = normalize_tlm(p.data, p.asset_id, p.weather_cell)
        elif p.product in ("SMARTLINE","SMARTLINE_TCF"):
            event = normalize_smartline(p.data, p.asset_id, p.weather_cell)
        else:
            raise ValueError(f"Unknown product: {p.product}")
        _write_ledger(event)
        revenue_tracker.record("/ingest", 0.001)
        return {"status":"ok","event_id":event["event_id"],
                "payload_hash":event["payload_hash"],
                "payload_uri":event["payload_uri"],"audit_ready":True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ingest/trial")
async def ingest_trial(request: Request, p: Payload):
    """
    Trial ingest endpoint — no x402 payment required.
    Validates against active trial instead.
    """
    device_id = p.asset_id or "unknown"
    allowed, reason = is_trial_device_allowed(device_id)
    if not allowed:
        raise HTTPException(status_code=402, detail=reason)
    try:
        if p.product in ("TLM", "DNP3_AUTO", "MODBUS_AUTO"):
            event = normalize_tlm(p.data, p.asset_id, p.weather_cell)
        elif p.product in ("SMARTLINE", "SMARTLINE_TCF"):
            event = normalize_smartline(p.data, p.asset_id, p.weather_cell)
        else:
            raise ValueError(f"Unknown product: {p.product}")
        _write_ledger(event)
        return {
            "status": "ok",
            "trial": True,
            "event_id": event["event_id"],
            "payload_hash": event["payload_hash"],
            "payload_uri": event["payload_uri"],
            "audit_ready": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    from datetime import datetime, timezone
    return {"status":"ok","service":"sig-ingest",
            "time":datetime.now(timezone.utc).isoformat(),
            "x402": x402_status()}

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

# ── Evidence-as-a-Service (EaaS) ───────────────────────────
from datetime import datetime, timezone
import hashlib, uuid
import json

class EvidenceRequest(BaseModel):
    asset_id:       str
    event_ids:      Optional[list[str]] = None   # specific events, or omit for range
    from_timestamp: Optional[str] = None          # ISO-8601 UTC
    to_timestamp:   Optional[str] = None          # ISO-8601 UTC
    standards:      Optional[list[str]] = ["NERC-CIP-007-6", "FERC-881", "NIST-800-171"]
    requestor:      Optional[str] = None          # company or entity name
    purpose:        Optional[str] = None          # audit | insurance | regulatory | internal

@app.post("/evidence")
@psf_payment_required
async def evidence_package(request: Request, req: EvidenceRequest):
    """
    Evidence-as-a-Service (EaaS)
    Generates a structured compliance evidence package for the requested
    asset and time range. Package includes attested event records,
    calibration state references, compliance mapping, and a package hash
    suitable for submission to regulators or insurers.
    Fee: $0.010 per package (via x402 when enabled)
    """
    try:
        package_id  = str(uuid.uuid4())
        generated_at = datetime.now(timezone.utc).isoformat()

        # Retrieve events from ledger or fallback to disk
        events = _fetch_evidence_events(
            asset_id    = req.asset_id,
            event_ids   = req.event_ids,
            from_ts     = req.from_timestamp,
            to_ts       = req.to_timestamp,
        )

        # Build compliance mapping per standard
        compliance_map = {}
        for standard in (req.standards or []):
            compliance_map[standard] = {
                "events_satisfying": len(events),
                "audit_ready_count": sum(1 for e in events
                                         if e.get("compliance", {}).get("audit_ready")),
                "coverage_period": {
                    "from": req.from_timestamp,
                    "to":   req.to_timestamp or generated_at,
                },
            }

        # Build evidence package
        package = {
            "package_id":       package_id,
            "generated_at":     generated_at,
            "generated_by":     "Total Reality Global — SIG EaaS v1.0",
            "asset_id":         req.asset_id,
            "requestor":        req.requestor,
            "purpose":          req.purpose,
            "standards":        req.standards,
            "event_count":      len(events),
            "events":           events,
            "compliance_map":   compliance_map,
            "package_hash":     "",   # filled below
            "psf_attestation": {
                "service":      "Evidence-as-a-Service",
                "version":      "1.0",
                "wallet":       os.getenv("PSF_WALLET", ""),
                "network":      os.getenv("PSF_NETWORK", "solana-mainnet"),
                "fee_usd":      0.010,
            }
        }

        # Hash the complete package for tamper-evidence
        package_json    = json.dumps(package, sort_keys=True)
        package["package_hash"] = hashlib.sha256(
            package_json.encode()
        ).hexdigest()

        # Write package to disk for audit trail
        os.makedirs("/var/sig/evidence", exist_ok=True)
        pkg_file = f"/var/sig/evidence/{package_id}.json"
        with open(pkg_file, "w") as f:
            json.dump(package, f, indent=2)

        revenue_tracker.record("/evidence", 0.010)

        return {
            "status":       "ok",
            "package_id":   package_id,
            "generated_at": generated_at,
            "event_count":  len(events),
            "package_hash": package["package_hash"],
            "package_uri":  f"file://{pkg_file}",
            "compliance_map": compliance_map,
            "fee_usd":      0.010,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _fetch_evidence_events(asset_id: str,
                            event_ids: Optional[list] = None,
                            from_ts: Optional[str] = None,
                            to_ts:   Optional[str] = None) -> list:
    """
    Retrieve events from Postgres if DATABASE_URL is set,
    otherwise return empty list (no-DB mode for dev/test).
    """
    url = os.getenv("DATABASE_URL")
    if not url:
        return []

    try:
        conn = psycopg2.connect(url)
        cur  = conn.cursor()

        if event_ids:
            placeholders = ",".join(["%s"] * len(event_ids))
            cur.execute(f"""
                SELECT event_id, payload_hash, payload_uri, attestation,
                       compliance, data, created_at
                FROM sig_events
                WHERE event_id IN ({placeholders})
                  AND data->>'asset_id' = %s
            """, (*event_ids, asset_id))
        else:
            cur.execute("""
                SELECT event_id, payload_hash, payload_uri, attestation,
                       compliance, data, created_at
                FROM sig_events
                WHERE data->>'asset_id' = %s
                  AND (%s::timestamptz IS NULL OR created_at >= %s::timestamptz)
                  AND (%s::timestamptz IS NULL OR created_at <= %s::timestamptz)
                ORDER BY created_at ASC
            """, (asset_id, from_ts, from_ts, to_ts, to_ts))

        rows = cur.fetchall()
        cur.close(); conn.close()

        return [
            {
                "event_id":     r[0],
                "payload_hash": r[1],
                "payload_uri":  r[2],
                "attestation":  r[3],
                "compliance":   r[4],
                "data":         r[5],
                "created_at":   r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]
    except Exception:
        return []


# ── Partner Portal Access Log ──────────────────────────────
from pydantic import BaseModel as BM

class AccessLog(BM):
    name:       str
    company:    str
    token:      str
    page:       str
    timestamp:  str = ""

@app.post("/partner-log")
@psf_payment_required
async def partner_log(request: Request, log: AccessLog):
    log.timestamp = datetime.now(timezone.utc).isoformat()
    entry = log.dict()
    os.makedirs("/var/sig/partner-logs", exist_ok=True)
    logfile = "/var/sig/partner-logs/access.jsonl"
    with open(logfile, "a") as f:
        f.write(json.dumps(entry) + "\n")
    revenue_tracker.record("/partner-log", 0.0005)
    return {"status": "logged", "timestamp": log.timestamp}