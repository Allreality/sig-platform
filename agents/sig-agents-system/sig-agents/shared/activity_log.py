"""
shared/activity_log.py
======================
Shared deterministic activity log for all SIG agents.
All agents write to a single JSONL file at /var/sig/agents/activity.jsonl
All entries are immutable once written — append only.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ACTIVITY_LOG_PATH = Path(os.environ.get("SIG_AGENT_LOG", "/var/sig/agents/activity.jsonl"))
X402_LEDGER_PATH = Path(os.environ.get("SIG_X402_LEDGER", "/var/sig/agents/x402_pending.jsonl"))


def _ensure_dirs():
    ACTIVITY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    X402_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)


def log_event(bot_name: str, action: str, detail: dict = None, level: str = "INFO"):
    """
    Append one event to the shared activity log.
    Format: {ts, bot, level, action, detail}
    """
    _ensure_dirs()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "bot": bot_name,
        "level": level,
        "action": action,
        "detail": detail or {},
    }
    with open(ACTIVITY_LOG_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def log_fee_event(bot_name: str, endpoint: str, fee_usd: float, reference_id: str, detail: dict = None):
    """
    Record an x402 fee event to the pending ledger.
    Fees are recorded but NOT settled until x402 is activated.
    """
    _ensure_dirs()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "bot": bot_name,
        "endpoint": endpoint,
        "fee_usd": fee_usd,
        "reference_id": reference_id,
        "status": "pending_activation",
        "wallet": "3Amc3tkRvijtrRtE6XVAkYd8UxF9VKqm7mqDdyT6FPWm",
        "network": "solana-mainnet",
        "currency": "USDC",
        "detail": detail or {},
    }
    with open(X402_LEDGER_PATH, "a") as f:
        f.write(json.dumps(entry) + "\n")
    log_event(bot_name, "fee_recorded", {"fee_usd": fee_usd, "ref": reference_id})
    return entry


def read_log(bot_name: str = None, last_n: int = 50) -> list:
    """Read recent log entries, optionally filtered by bot name."""
    _ensure_dirs()
    if not ACTIVITY_LOG_PATH.exists():
        return []
    entries = []
    with open(ACTIVITY_LOG_PATH) as f:
        for line in f:
            try:
                e = json.loads(line.strip())
                if bot_name is None or e.get("bot") == bot_name:
                    entries.append(e)
            except Exception:
                continue
    return entries[-last_n:]


def read_pending_fees() -> list:
    """Read all pending x402 fee events."""
    _ensure_dirs()
    if not X402_LEDGER_PATH.exists():
        return []
    fees = []
    with open(X402_LEDGER_PATH) as f:
        for line in f:
            try:
                fees.append(json.loads(line.strip()))
            except Exception:
                continue
    return fees
