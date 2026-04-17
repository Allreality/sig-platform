"""
bots/partner_followup.py
========================
Bot 1 — Partner Follow-Up Bot
Tracks outreach to Lindsey Systems, SEL, Siemens Energy,
and NERC compliance contacts. Manages follow-up timing.
Escalates to human only when a reply is received.

Operates READ-ONLY on partner ledger except for state updates.
Does NOT send emails autonomously — flags when human action required.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from shared.activity_log import log_event, log_fee_event
from shared.aeo_schema import PARTNER_LOG_DIR, AGENT_STATE_DIR

BOT_NAME = "partner_followup"
STATE_FILE = Path(AGENT_STATE_DIR) / "partner_followup_state.json"

# Partner registry — update as contacts are added
PARTNERS = {
    "lindsey_systems": {
        "name": "Lindsey Systems",
        "contact": "Dr. Keith Lindsey",
        "email": "mail@lindsey-usa.com",
        "channel": "email",
        "type": "hardware_partner",
        "initial_outreach": "2026-02-21",
        "follow_up_days": [7, 14, 21],
        "notes": "TLM/SMARTLINE adapters built. Primary hardware target.",
    },
    "sel": {
        "name": "Schweitzer Engineering Laboratories",
        "contact": "Scott George",
        "email": None,
        "channel": "email",
        "type": "hardware_partner",
        "initial_outreach": "2026-02-21",
        "follow_up_days": [7, 14, 21],
        "notes": "Grid protection and automation. NERC CIP aligned.",
    },
    "siemens_energy": {
        "name": "Siemens Energy",
        "contact": "Supplier Innovation Portal",
        "email": "ecosystem.siemens.com",
        "channel": "portal",
        "type": "hardware_partner",
        "initial_outreach": "2026-02-21",
        "follow_up_days": [14, 28],
        "notes": "Gridscale X. Portal submission in progress. 14-day response SLA.",
    },
    "cecil_elie": {
        "name": "Cecil Elie",
        "contact": "PSEG Long Island",
        "email": None,
        "channel": "linkedin_inmail",
        "type": "nerc_compliance_contact",
        "initial_outreach": "2026-02-22",
        "follow_up_days": [5, 10],
        "notes": "NERC/CIP Compliance Project Manager. Large utility.",
    },
    "holly_haynes": {
        "name": "Holly Haynes",
        "contact": "VELCO Vermont",
        "email": None,
        "channel": "linkedin_inmail",
        "type": "nerc_compliance_contact",
        "initial_outreach": "2026-02-22",
        "follow_up_days": [5, 10],
        "notes": "Manager NERC Compliance. Transmission-only utility. FERC 881 directly applicable.",
    },
    "bryant_hall": {
        "name": "Bryant Hall",
        "contact": "RWE",
        "email": None,
        "channel": "linkedin_inmail",
        "type": "nerc_compliance_contact",
        "initial_outreach": "2026-02-22",
        "follow_up_days": [5, 10],
        "notes": "Senior Manager NERC CIP. Cyber + CIP combined role.",
    },
    "manuel_sanchez": {
        "name": "Manuel Sanchez",
        "contact": "Oncor Electric Delivery",
        "email": None,
        "channel": "linkedin_inmail",
        "type": "nerc_compliance_contact",
        "initial_outreach": "2026-02-22",
        "follow_up_days": [5, 10],
        "notes": "Manager Transmission Planning NERC Compliance. Texas transmission.",
    },
    "olayimika": {
        "name": "Olayimika Oyebanji",
        "contact": "Legal Advisor",
        "email": None,
        "channel": "linkedin",
        "type": "legal_advisor",
        "initial_outreach": "2026-02-21",
        "follow_up_days": [2, 5],
        "notes": "Blockchain lawyer. 10 questions sent. Call requested. He/him, Africa.",
    },
}


def _load_state() -> dict:
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {k: {"status": "awaiting_response", "follow_ups_sent": [], "replied": False, "notes": []} for k in PARTNERS}


def _save_state(state: dict):
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _days_since(date_str: str) -> int:
    outreach_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - outreach_date).days


def run() -> dict:
    """
    Main run loop for partner follow-up bot.
    Returns a report dict with escalations and due follow-ups.
    """
    log_event(BOT_NAME, "run_start")
    state = _load_state()
    report = {
        "escalations_required": [],
        "follow_ups_due": [],
        "waiting": [],
        "replied": [],
    }

    now = datetime.now(timezone.utc)

    for partner_id, partner in PARTNERS.items():
        pstate = state.get(partner_id, {"status": "awaiting_response", "follow_ups_sent": [], "replied": False, "notes": []})
        days_elapsed = _days_since(partner["initial_outreach"])

        if pstate.get("replied"):
            report["replied"].append({
                "partner": partner["name"],
                "contact": partner["contact"],
                "action": "HUMAN_REQUIRED — reply received, review and respond",
            })
            log_event(BOT_NAME, "reply_pending_human_review", {"partner": partner["name"]}, level="WARN")
            continue

        # Check which follow-ups are due
        for follow_up_day in partner["follow_up_days"]:
            if days_elapsed >= follow_up_day and follow_up_day not in pstate["follow_ups_sent"]:
                report["follow_ups_due"].append({
                    "partner": partner["name"],
                    "contact": partner["contact"],
                    "channel": partner["channel"],
                    "day": follow_up_day,
                    "action": f"SEND FOLLOW-UP via {partner['channel']} — day {follow_up_day}",
                    "notes": partner["notes"],
                })
                log_event(BOT_NAME, "follow_up_due", {
                    "partner": partner["name"],
                    "day": follow_up_day,
                    "channel": partner["channel"],
                }, level="WARN")

        # Check for overdue (past last follow-up day with no reply)
        max_follow_up = max(partner["follow_up_days"]) if partner["follow_up_days"] else 21
        if days_elapsed > max_follow_up and not pstate.get("replied"):
            report["escalations_required"].append({
                "partner": partner["name"],
                "contact": partner["contact"],
                "days_elapsed": days_elapsed,
                "action": "ESCALATE — no response after max follow-up window",
            })
            log_event(BOT_NAME, "escalation_required", {
                "partner": partner["name"],
                "days_elapsed": days_elapsed,
            }, level="ERROR")
        else:
            report["waiting"].append({
                "partner": partner["name"],
                "days_elapsed": days_elapsed,
                "status": pstate["status"],
            })

    _save_state(state)
    log_event(BOT_NAME, "run_complete", {
        "escalations": len(report["escalations_required"]),
        "follow_ups_due": len(report["follow_ups_due"]),
        "replied": len(report["replied"]),
    })
    return report


def mark_replied(partner_id: str, notes: str = ""):
    """Call this when a human reply is received from a partner."""
    state = _load_state()
    if partner_id in state:
        state[partner_id]["replied"] = True
        state[partner_id]["status"] = "reply_received"
        state[partner_id]["notes"].append({"ts": datetime.now(timezone.utc).isoformat(), "note": notes})
        _save_state(state)
        log_event(BOT_NAME, "reply_received", {"partner_id": partner_id, "notes": notes}, level="INFO")


def mark_followup_sent(partner_id: str, day: int):
    """Call this after a follow-up is manually sent."""
    state = _load_state()
    if partner_id in state:
        if day not in state[partner_id]["follow_ups_sent"]:
            state[partner_id]["follow_ups_sent"].append(day)
        _save_state(state)
        log_event(BOT_NAME, "followup_sent", {"partner_id": partner_id, "day": day})


if __name__ == "__main__":
    report = run()
    print(json.dumps(report, indent=2))
