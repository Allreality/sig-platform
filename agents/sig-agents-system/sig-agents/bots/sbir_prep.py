"""
bots/sbir_prep.py
=================
Bot 5 — SBIR Prep Bot
Tracks DOE/DHS SBIR submission readiness.
Maintains checklist, deadlines, document status.
Does not file anything autonomously — prepares and tracks.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from shared.activity_log import log_event
from shared.aeo_schema import AGENT_STATE_DIR

BOT_NAME = "sbir_prep"
STATE_FILE = Path(AGENT_STATE_DIR) / "sbir_prep_state.json"
SBIR_DIR = Path("/var/sig/sbir")

# SBIR document checklist aligned with SIG capabilities
SBIR_CHECKLIST = {
    "registration": [
        {"id": "ein", "item": "IRS EIN obtained", "status": "COMPLETE", "value": "41-4390000"},
        {"id": "sam_gov", "item": "SAM.gov registration submitted", "status": "PENDING", "value": "INC-GSAFSD20725720"},
        {"id": "uei_cage", "item": "UEI and CAGE code assigned", "status": "PENDING", "value": None},
        {"id": "sbir_reg", "item": "SBIR.gov account created", "status": "UNKNOWN", "value": None},
    ],
    "technical_documents": [
        {"id": "tech_abstract", "item": "Technical Abstract (250 words)", "status": "PENDING", "value": None},
        {"id": "project_narrative", "item": "Project Narrative (Phase I — 6 pages max)", "status": "PENDING", "value": None},
        {"id": "commercialization", "item": "Commercialization Plan", "status": "PENDING", "value": None},
        {"id": "budget_justification", "item": "Budget Justification", "status": "PENDING", "value": None},
        {"id": "facilities", "item": "Facilities & Equipment statement", "status": "PENDING", "value": None},
        {"id": "references", "item": "References cited", "status": "PENDING", "value": None},
    ],
    "ip_documents": [
        {"id": "sig_patent", "item": "SIG provisional patent — USPTO 63/983,517", "status": "COMPLETE", "value": "Filed Feb 15 2026"},
        {"id": "midnight_patent", "item": "Midnight provisional — USPTO 63/917,456", "status": "COMPLETE", "value": "Filed Nov 14 2025"},
        {"id": "psf_patent", "item": "PSF provisional patent", "status": "PENDING", "value": "In preparation"},
        {"id": "ip_assignment", "item": "IP assignment to LLC/entity", "status": "PENDING", "value": "Pending LLC formation"},
    ],
    "capabilities": [
        {"id": "live_system", "item": "Live deployed system", "status": "COMPLETE", "value": "SIG on VPSBG 87.121.52.49"},
        {"id": "benchmarks", "item": "Performance benchmarks", "status": "COMPLETE", "value": "9-14ms latency, ~70 req/sec"},
        {"id": "nerc_cip", "item": "NERC CIP-007-6 compliance evidence", "status": "COMPLETE", "value": "EaaS tested"},
        {"id": "ferc_881", "item": "FERC Order 881 compliance evidence", "status": "COMPLETE", "value": "EaaS tested"},
        {"id": "hardware_attest", "item": "AMD SEV-SNP hardware attestation", "status": "COMPLETE", "value": "Live on VPSBG"},
        {"id": "partner_loi", "item": "Letter of Intent from hardware partner", "status": "PENDING", "value": "Awaiting Lindsey/SEL response"},
    ],
}

# Target agencies and solicitations
TARGET_SOLICITATIONS = [
    {
        "agency": "DOE",
        "office": "Office of Electricity",
        "topic": "Grid Security and Resilience",
        "sbir_phase": "Phase I",
        "award_target": "$200,000-$300,000",
        "alignment": "SIG hardware-attested NERC CIP compliance for transmission infrastructure",
        "status": "Program frozen — watch for reauthorization",
    },
    {
        "agency": "DHS",
        "office": "Science and Technology Directorate",
        "topic": "Critical Infrastructure Protection",
        "sbir_phase": "Phase I",
        "award_target": "$200,000-$300,000",
        "alignment": "SIG real-time attestation layer for bulk electric system cyber assets",
        "status": "Program frozen — watch for reauthorization",
    },
]


def _load_state() -> dict:
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"checklist": SBIR_CHECKLIST, "last_updated": None}


def _save_state(state: dict):
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def update_item(category: str, item_id: str, status: str, value: str = None):
    """Update the status of a checklist item."""
    state = _load_state()
    checklist = state.get("checklist", SBIR_CHECKLIST)
    if category in checklist:
        for item in checklist[category]:
            if item["id"] == item_id:
                item["status"] = status
                if value:
                    item["value"] = value
                item["updated_at"] = datetime.now(timezone.utc).isoformat()
                break
    state["checklist"] = checklist
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
    log_event(BOT_NAME, "checklist_updated", {"category": category, "item_id": item_id, "status": status})


def run() -> dict:
    """Main run loop — generate readiness report."""
    log_event(BOT_NAME, "run_start")
    state = _load_state()
    checklist = state.get("checklist", SBIR_CHECKLIST)

    # Count completion
    total = 0
    complete = 0
    pending = []

    for category, items in checklist.items():
        for item in items:
            total += 1
            if item["status"] == "COMPLETE":
                complete += 1
            else:
                pending.append({
                    "category": category,
                    "item": item["item"],
                    "id": item["id"],
                    "status": item["status"],
                })

    readiness_pct = round((complete / total) * 100, 1) if total > 0 else 0

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "readiness_pct": readiness_pct,
        "complete": complete,
        "total": total,
        "pending_items": pending,
        "target_solicitations": TARGET_SOLICITATIONS,
        "blocking_items": [p for p in pending if p["category"] in ["registration", "ip_documents"]],
        "recommendation": (
            "SBIR applications cannot be submitted until SAM.gov approval and UEI/CAGE code received. "
            "Continue preparing technical documents and IP assignment in parallel."
        ),
    }

    # Save report
    SBIR_DIR.mkdir(parents=True, exist_ok=True)
    report_path = SBIR_DIR / "sbir_readiness.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    log_event(BOT_NAME, "run_complete", {
        "readiness_pct": readiness_pct,
        "pending_count": len(pending),
        "blocking_count": len(report["blocking_items"]),
    })

    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
