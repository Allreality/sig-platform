"""
bots/legal_coordination.py
==========================
Bot 6 — Legal Coordination Bot
Tracks questions, responses, and timelines for
IP assignment, LLC formation, and patent strategy.
Supports work with Olayimika Oyebanji.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from shared.activity_log import log_event
from shared.aeo_schema import AGENT_STATE_DIR

BOT_NAME = "legal_coordination"
STATE_FILE = Path(AGENT_STATE_DIR) / "legal_coordination_state.json"
LEGAL_DIR = Path("/var/sig/legal")

# Questions sent to Olayimika Feb 21 2026
OLAYIMIKA_QUESTIONS = [
    {"id": "q1", "q": "Can we file the non-provisional pro se or do we need a patent attorney? Cost difference?", "status": "PENDING"},
    {"id": "q2", "q": "Risk of self-filing a technology patent with 15 claims?", "status": "PENDING"},
    {"id": "q3", "q": "Can the provisional spec (79-93 pages) convert directly or needs restructuring?", "status": "PENDING"},
    {"id": "q4", "q": "Second provisional 63/917,456 (Nov 14 2026 deadline) — file non-provisional first?", "status": "PENDING"},
    {"id": "q5", "q": "Claims strategy — broad independent claims first, narrow dependent after?", "status": "PENDING"},
    {"id": "q6", "q": "Should Total Reality Global convert to LLC before signing any partnership agreements?", "status": "PENDING"},
    {"id": "q7", "q": "What licensing structure protects IP while allowing commercial use?", "status": "PENDING"},
    {"id": "q8", "q": "If LLC formed, is IP assignment automatic or needs separate agreement?", "status": "PENDING"},
    {"id": "q9", "q": "Standard structure for 3% equity advisor agreement at pre-revenue stage?", "status": "PENDING"},
    {"id": "q10", "q": "Equity vesting — time-based or milestone-triggered for advisors?", "status": "PENDING"},
]

# Legal timeline items
LEGAL_TIMELINE = [
    {
        "id": "call_olayimika",
        "item": "Schedule call with Olayimika this week",
        "priority": "URGENT",
        "status": "PENDING",
        "deadline": None,
        "notes": "10 questions sent via LinkedIn Feb 21 2026. Response received: positive.",
    },
    {
        "id": "llc_formation",
        "item": "LLC formation — Total Reality Global",
        "priority": "HIGH",
        "status": "PENDING",
        "deadline": "Before first partnership agreement signed",
        "notes": "Must precede IP assignment and partner contracts.",
    },
    {
        "id": "ip_assignment",
        "item": "IP assignment from sole proprietor to LLC",
        "priority": "HIGH",
        "status": "PENDING",
        "deadline": "After LLC formation",
        "notes": "Both patents must be assigned. PSF provisional also when filed.",
    },
    {
        "id": "psf_provisional",
        "item": "File PSF provisional patent",
        "priority": "HIGH",
        "status": "PENDING",
        "deadline": "Before partner NDA disclosures",
        "notes": "PSF Patent Narrative v0.1 complete with 10 draft claims. Discuss with Olayimika before filing.",
    },
    {
        "id": "midnight_nonprovisional",
        "item": "File Midnight Compliance non-provisional",
        "priority": "HIGH",
        "status": "PENDING",
        "deadline": "2026-11-14",
        "notes": "USPTO 63/917,456. 12 months from provisional. Akil can file pro se.",
    },
    {
        "id": "sig_nonprovisional",
        "item": "File SIG non-provisional",
        "priority": "MEDIUM",
        "status": "PENDING",
        "deadline": "2027-02-15",
        "notes": "USPTO 63/983,517. 12 months from provisional. Akil can file pro se.",
    },
    {
        "id": "advisor_agreement",
        "item": "Formalize Olayimika advisor equity agreement",
        "priority": "MEDIUM",
        "status": "PENDING",
        "deadline": None,
        "notes": "Standard 3% equity, vesting TBD after call.",
    },
    {
        "id": "partner_nda",
        "item": "NDA template for partner disclosures",
        "priority": "MEDIUM",
        "status": "PENDING",
        "deadline": "Before Siemens responds",
        "notes": "Siemens requires NDA before exchanging confidential information.",
    },
]


def _load_state() -> dict:
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "questions": OLAYIMIKA_QUESTIONS,
        "timeline": LEGAL_TIMELINE,
        "last_updated": None,
    }


def _save_state(state: dict):
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def update_question(question_id: str, status: str, answer: str = None):
    """Mark a question as answered."""
    state = _load_state()
    for q in state.get("questions", []):
        if q["id"] == question_id:
            q["status"] = status
            if answer:
                q["answer"] = answer
                q["answered_at"] = datetime.now(timezone.utc).isoformat()
            break
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
    log_event(BOT_NAME, "question_updated", {"question_id": question_id, "status": status})


def update_timeline_item(item_id: str, status: str, notes: str = None):
    """Update the status of a legal timeline item."""
    state = _load_state()
    for item in state.get("timeline", []):
        if item["id"] == item_id:
            item["status"] = status
            if notes:
                item["notes"] = notes
            item["updated_at"] = datetime.now(timezone.utc).isoformat()
            break
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_state(state)
    log_event(BOT_NAME, "timeline_updated", {"item_id": item_id, "status": status})


def run() -> dict:
    """Main run loop — generate legal coordination report."""
    log_event(BOT_NAME, "run_start")
    state = _load_state()

    questions = state.get("questions", OLAYIMIKA_QUESTIONS)
    timeline = state.get("timeline", LEGAL_TIMELINE)

    pending_questions = [q for q in questions if q["status"] == "PENDING"]
    answered_questions = [q for q in questions if q["status"] != "PENDING"]
    urgent_items = [t for t in timeline if t["priority"] == "URGENT" and t["status"] == "PENDING"]
    high_items = [t for t in timeline if t["priority"] == "HIGH" and t["status"] == "PENDING"]

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "olayimika_questions": {
            "total": len(questions),
            "pending": len(pending_questions),
            "answered": len(answered_questions),
            "pending_list": pending_questions,
        },
        "timeline": {
            "urgent": urgent_items,
            "high_priority": high_items,
            "all": timeline,
        },
        "critical_path": [
            "1. Olayimika call this week",
            "2. LLC formation (before any partnership agreement)",
            "3. IP assignment (after LLC)",
            "4. PSF provisional filing (before Siemens NDA discussion)",
            "5. Midnight non-provisional by Nov 14 2026",
        ],
    }

    # Save report
    LEGAL_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEGAL_DIR / "legal_status.json", "w") as f:
        json.dump(report, f, indent=2)

    log_event(BOT_NAME, "run_complete", {
        "pending_questions": len(pending_questions),
        "urgent_items": len(urgent_items),
    })

    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
