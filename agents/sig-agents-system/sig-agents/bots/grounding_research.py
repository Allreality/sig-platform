"""
bots/grounding_research.py
==========================
Bot 4 — Grounding Research Bot
Analyzes raw sensor data, flags anomalies,
generates grounding reports with IEEE references.
Records $0.050/report billing entries for x402.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from shared.activity_log import log_event, log_fee_event
from shared.aeo_schema import X402_PRICING, AGENT_STATE_DIR, SIG_EVENTS_TABLE
import os

BOT_NAME = "grounding_research"
STATE_FILE = Path(AGENT_STATE_DIR) / "grounding_research_state.json"
REPORT_DIR = Path("/var/sig/grounding-reports")
DATABASE_URL = os.environ.get("DATABASE_URL")

# IEEE grounding standards reference
IEEE_STANDARDS = {
    "IEEE_80": "Guide for Safety in AC Substation Grounding",
    "IEEE_142": "Recommended Practice for Grounding of Industrial and Commercial Power Systems",
    "IEEE_1100": "Recommended Practice for Powering and Grounding Electronic Equipment",
    "NERC_CIP_006": "Physical Security of BES Cyber Systems",
    "NERC_CIP_007": "Systems Security Management",
}

# Anomaly detection thresholds
ANOMALY_THRESHOLDS = {
    "current_rms_amps": {"warn": 400, "critical": 500},
    "conductor_temp_celsius": {"warn": 75, "critical": 90},
    "clearance_to_ground_m": {"warn": 7.0, "critical": 6.0},
    "load_percentage": {"warn": 85, "critical": 95},
}


def _fetch_recent_events(limit: int = 100) -> list:
    """Pull recent events from Neon Postgres for analysis."""
    if not DATABASE_URL:
        log_event(BOT_NAME, "db_unavailable", {"reason": "DATABASE_URL not set"}, level="WARN")
        return []
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"SELECT * FROM {SIG_EVENTS_TABLE} ORDER BY created_at DESC LIMIT %s",
                (limit,)
            )
            events = [dict(r) for r in cur.fetchall()]
        conn.close()
        return events
    except Exception as ex:
        log_event(BOT_NAME, "db_fetch_error", {"error": str(ex)}, level="ERROR")
        return []


def _analyze_event(event: dict) -> dict:
    """
    Analyze a single event for grounding anomalies.
    Returns anomaly findings and severity.
    """
    findings = []
    severity = "NOMINAL"
    data = event.get("data", {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            data = {}

    for field, thresholds in ANOMALY_THRESHOLDS.items():
        value = data.get(field)
        if value is None:
            continue
        if field in ["clearance_to_ground_m"]:
            # Lower is worse for clearance
            if value <= thresholds["critical"]:
                findings.append({"field": field, "value": value, "severity": "CRITICAL",
                                  "threshold": thresholds["critical"], "direction": "below"})
                severity = "CRITICAL"
            elif value <= thresholds["warn"]:
                findings.append({"field": field, "value": value, "severity": "WARNING",
                                  "threshold": thresholds["warn"], "direction": "below"})
                if severity != "CRITICAL":
                    severity = "WARNING"
        else:
            # Higher is worse for current, temp, load
            if value >= thresholds["critical"]:
                findings.append({"field": field, "value": value, "severity": "CRITICAL",
                                  "threshold": thresholds["critical"], "direction": "above"})
                severity = "CRITICAL"
            elif value >= thresholds["warn"]:
                findings.append({"field": field, "value": value, "severity": "WARNING",
                                  "threshold": thresholds["warn"], "direction": "above"})
                if severity != "CRITICAL":
                    severity = "WARNING"

    return {
        "event_id": event.get("event_id"),
        "asset_id": event.get("data", {}).get("asset_id") if isinstance(event.get("data"), dict) else None,
        "findings": findings,
        "severity": severity,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
    }


def generate_report(events: list = None, asset_id: str = None) -> dict:
    """
    Generate a grounding analysis report.
    IEEE-referenced findings. Records $0.050 x402 fee.
    """
    if events is None:
        events = _fetch_recent_events()

    if asset_id:
        events = [e for e in events if
                  (e.get("data") or {}).get("asset_id") == asset_id
                  if isinstance(e.get("data"), dict)]

    report_id = str(uuid.uuid4())
    generated_at = datetime.now(timezone.utc).isoformat()

    analyses = [_analyze_event(e) for e in events]
    critical = [a for a in analyses if a["severity"] == "CRITICAL"]
    warnings = [a for a in analyses if a["severity"] == "WARNING"]
    nominal = [a for a in analyses if a["severity"] == "NOMINAL"]

    report = {
        "report_id": report_id,
        "generated_at": generated_at,
        "generated_by": BOT_NAME,
        "asset_id": asset_id or "all",
        "events_analyzed": len(events),
        "summary": {
            "critical_count": len(critical),
            "warning_count": len(warnings),
            "nominal_count": len(nominal),
            "overall_status": "CRITICAL" if critical else ("WARNING" if warnings else "NOMINAL"),
        },
        "findings": {
            "critical": critical,
            "warnings": warnings,
        },
        "ieee_references": IEEE_STANDARDS,
        "recommendations": _build_recommendations(critical, warnings),
        "billing": {
            "fee_usd": X402_PRICING["/grounding"],
            "endpoint": "/grounding",
            "status": "pending_x402_activation",
            "wallet": "3Amc3tkRvijtrRtE6XVAkYd8UxF9VKqm7mqDdyT6FPWm",
        },
    }

    # Write report
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{report_id}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    # Record x402 fee
    log_fee_event(
        bot_name=BOT_NAME,
        endpoint="/grounding",
        fee_usd=X402_PRICING["/grounding"],
        reference_id=report_id,
        detail={"events_analyzed": len(events), "critical": len(critical)},
    )

    log_event(BOT_NAME, "report_generated", {
        "report_id": report_id,
        "critical": len(critical),
        "warnings": len(warnings),
        "path": str(report_path),
    })

    return report


def _build_recommendations(critical: list, warnings: list) -> list:
    """Generate IEEE-referenced recommendations from findings."""
    recs = []
    fields_seen = set()

    for finding_set in [critical, warnings]:
        for analysis in finding_set:
            for finding in analysis.get("findings", []):
                field = finding["field"]
                if field in fields_seen:
                    continue
                fields_seen.add(field)

                if field == "clearance_to_ground_m":
                    recs.append({
                        "field": field,
                        "severity": finding["severity"],
                        "recommendation": "Inspect conductor sag and tower geometry. Verify clearance per NERC FAC-001 and IEEE 80 step/touch potential requirements.",
                        "ieee_ref": "IEEE_80",
                    })
                elif field == "conductor_temp_celsius":
                    recs.append({
                        "field": field,
                        "severity": finding["severity"],
                        "recommendation": "Reduce load or activate dynamic line rating. Conductor annealing risk above 75°C per IEEE 738.",
                        "ieee_ref": "IEEE_142",
                    })
                elif field == "current_rms_amps":
                    recs.append({
                        "field": field,
                        "severity": finding["severity"],
                        "recommendation": "Review line rating. Consult SMARTLINE DLR capacity before further loading.",
                        "ieee_ref": "IEEE_80",
                    })
                elif field == "load_percentage":
                    recs.append({
                        "field": field,
                        "severity": finding["severity"],
                        "recommendation": "Load shedding or rerouting recommended. NERC CIP-007-6 operational awareness required.",
                        "ieee_ref": "NERC_CIP_007",
                    })
    return recs


def run() -> dict:
    """Main run loop for grounding research bot."""
    log_event(BOT_NAME, "run_start")
    events = _fetch_recent_events()

    if not events:
        log_event(BOT_NAME, "no_events", {"message": "No events to analyze"}, level="WARN")
        return {"status": "no_events", "report": None}

    report = generate_report(events=events)
    log_event(BOT_NAME, "run_complete", {
        "report_id": report["report_id"],
        "overall_status": report["summary"]["overall_status"],
    })
    return {"status": "ok", "report": report}


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, default=str))
