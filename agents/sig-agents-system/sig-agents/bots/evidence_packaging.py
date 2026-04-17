"""
bots/evidence_packaging.py
===========================
Bot 2 — Evidence Packaging Bot
Automates EaaS workflows. Pulls events from Neon Postgres,
generates compliance packages, stores to evidence directory,
records x402 fee events.

Does NOT modify SIG core logic or AEO schema.
"""

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras

from shared.activity_log import log_event, log_fee_event
from shared.aeo_schema import (
    SUPPORTED_STANDARDS, EVIDENCE_DIR, SIG_EVENTS_TABLE,
    X402_PRICING, AGENT_STATE_DIR
)

BOT_NAME = "evidence_packaging"
STATE_FILE = Path(AGENT_STATE_DIR) / "evidence_packaging_state.json"
DATABASE_URL = os.environ.get("DATABASE_URL")


def _get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL not set — cannot connect to Neon Postgres")
    return psycopg2.connect(DATABASE_URL)


def _load_state() -> dict:
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"last_packaged_at": None, "total_packages": 0, "total_events_processed": 0}


def _save_state(state: dict):
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _fetch_unpackaged_events(asset_id: str = None, limit: int = 100) -> list:
    """Pull recent events from Neon Postgres."""
    conn = _get_db()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if asset_id:
                cur.execute(
                    f"SELECT * FROM {SIG_EVENTS_TABLE} WHERE data->>'asset_id' = %s ORDER BY created_at DESC LIMIT %s",
                    (asset_id, limit)
                )
            else:
                cur.execute(
                    f"SELECT * FROM {SIG_EVENTS_TABLE} ORDER BY created_at DESC LIMIT %s",
                    (limit,)
                )
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


def _build_compliance_map(events: list, standards: list) -> dict:
    """
    Build compliance map from events.
    Deterministic — same events + standards = same map.
    """
    compliance_map = {}
    timestamps = [e["created_at"] for e in events if e.get("created_at")]

    for standard in standards:
        audit_ready = [e for e in events if e.get("compliance", {}).get(standard, {}).get("audit_ready", True)]
        compliance_map[standard] = {
            "events_satisfying": len(audit_ready),
            "audit_ready_count": len(audit_ready),
            "coverage_period": {
                "from": min(str(t) for t in timestamps) if timestamps else None,
                "to": max(str(t) for t in timestamps) if timestamps else datetime.now(timezone.utc).isoformat(),
            }
        }
    return compliance_map


def generate_package(
    asset_id: str,
    standards: list = None,
    requestor: str = "evidence_packaging_bot",
    purpose: str = "automated_compliance",
    event_ids: list = None,
) -> dict:
    """
    Generate one compliance evidence package.
    Writes to /var/sig/evidence/.
    Records x402 fee event (pending, not settled).
    """
    if standards is None:
        standards = SUPPORTED_STANDARDS

    log_event(BOT_NAME, "package_generation_start", {
        "asset_id": asset_id,
        "standards": standards,
        "requestor": requestor,
    })

    # Fetch events
    try:
        events = _fetch_unpackaged_events(asset_id=asset_id)
        if event_ids:
            events = [e for e in events if e.get("event_id") in event_ids]
    except Exception as ex:
        log_event(BOT_NAME, "db_fetch_error", {"error": str(ex)}, level="ERROR")
        events = []

    package_id = str(uuid.uuid4())
    generated_at = datetime.now(timezone.utc).isoformat()
    compliance_map = _build_compliance_map(events, standards)

    package = {
        "package_id": package_id,
        "asset_id": asset_id,
        "generated_at": generated_at,
        "generated_by": BOT_NAME,
        "requestor": requestor,
        "purpose": purpose,
        "standards": standards,
        "event_count": len(events),
        "events": events,
        "compliance_map": compliance_map,
        "psf_attestation": {
            "service": "sig-ingest",
            "version": "1.0.0",
            "wallet": "3Amc3tkRvijtrRtE6XVAkYd8UxF9VKqm7mqDdyT6FPWm",
            "network": "solana-mainnet",
            "fee_usd": X402_PRICING["/evidence"],
            "fee_status": "pending_x402_activation",
        },
    }

    # Compute package hash
    package_bytes = json.dumps(package, sort_keys=True, default=str).encode()
    package["package_hash"] = hashlib.sha256(package_bytes).hexdigest()

    # Write to evidence directory
    Path(EVIDENCE_DIR).mkdir(parents=True, exist_ok=True)
    evidence_path = Path(EVIDENCE_DIR) / f"{package_id}.json"
    with open(evidence_path, "w") as f:
        json.dump(package, f, indent=2, default=str)

    # Record x402 fee event
    log_fee_event(
        bot_name=BOT_NAME,
        endpoint="/evidence",
        fee_usd=X402_PRICING["/evidence"],
        reference_id=package_id,
        detail={"asset_id": asset_id, "event_count": len(events)},
    )

    log_event(BOT_NAME, "package_generated", {
        "package_id": package_id,
        "event_count": len(events),
        "path": str(evidence_path),
    })

    return {
        "status": "ok",
        "package_id": package_id,
        "generated_at": generated_at,
        "event_count": len(events),
        "package_hash": package["package_hash"],
        "package_uri": f"file://{evidence_path}",
        "compliance_map": compliance_map,
        "fee_usd": X402_PRICING["/evidence"],
        "fee_status": "pending_x402_activation",
    }


def run(asset_ids: list = None) -> dict:
    """
    Main run loop — generate packages for all known assets or specified list.
    """
    log_event(BOT_NAME, "run_start")
    state = _load_state()
    results = []

    # If no asset_ids provided, pull distinct assets from DB
    if not asset_ids:
        try:
            conn = _get_db()
            with conn.cursor() as cur:
                cur.execute(f"SELECT DISTINCT data->>'asset_id' FROM {SIG_EVENTS_TABLE} WHERE data->>'asset_id' IS NOT NULL")
                asset_ids = [row[0] for row in cur.fetchall()]
            conn.close()
        except Exception as ex:
            log_event(BOT_NAME, "asset_fetch_error", {"error": str(ex)}, level="ERROR")
            asset_ids = []

    for asset_id in asset_ids:
        result = generate_package(asset_id=asset_id)
        results.append(result)
        state["total_packages"] += 1

    state["last_packaged_at"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)

    log_event(BOT_NAME, "run_complete", {
        "packages_generated": len(results),
        "total_packages_all_time": state["total_packages"],
    })
    return {"packages_generated": len(results), "results": results}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, default=str))
