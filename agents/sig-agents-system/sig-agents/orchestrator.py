"""
orchestrator.py
===============
SIG Agent Orchestrator — runs all 7 bots in sequence.
Each bot operates independently and writes to the shared activity log.
No bot modifies SIG core logic or AEO schema.
x402 fees are recorded but not settled until activation.

Usage:
    python orchestrator.py              # Run all bots
    python orchestrator.py --bot NAME   # Run specific bot
    python orchestrator.py --status     # Print activity log summary
    python orchestrator.py --fees       # Print pending x402 fee ledger
"""

import argparse
import os
from pathlib import Path

# Load .env if present
_env_file = Path(__file__).parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure shared modules are importable
sys.path.insert(0, str(Path(__file__).parent))

from shared.activity_log import log_event, read_log, read_pending_fees

BOT_REGISTRY = {
    "partner_followup":    ("bots.partner_followup",    "Partner Follow-Up Bot"),
    "evidence_packaging":  ("bots.evidence_packaging",  "Evidence Packaging Bot"),
    "health_monitor":      ("bots.health_monitor",      "VPSBG Health Monitor Bot"),
    "grounding_research":  ("bots.grounding_research",  "Grounding Research Bot"),
    "sbir_prep":           ("bots.sbir_prep",           "SBIR Prep Bot"),
    "legal_coordination":  ("bots.legal_coordination",  "Legal Coordination Bot"),
    "r2_telemetry":        ("bots.r2_telemetry",        "R2 Telemetry Bot"),
}

ORCHESTRATOR_NAME = "orchestrator"


def _import_bot(module_path: str):
    import importlib
    return importlib.import_module(module_path)


def run_bot(bot_key: str) -> dict:
    """Import and run a single bot. Returns its report."""
    module_path, display_name = BOT_REGISTRY[bot_key]
    log_event(ORCHESTRATOR_NAME, f"starting_{bot_key}", {"bot": display_name})
    try:
        mod = _import_bot(module_path)
        result = mod.run()
        log_event(ORCHESTRATOR_NAME, f"completed_{bot_key}", {"status": "ok"})
        return {"bot": bot_key, "name": display_name, "status": "ok", "result": result}
    except Exception as ex:
        log_event(ORCHESTRATOR_NAME, f"failed_{bot_key}", {"error": str(ex)}, level="ERROR")
        return {"bot": bot_key, "name": display_name, "status": "error", "error": str(ex)}


def run_all() -> dict:
    """Run all bots in sequence. Each bot is independent."""
    log_event(ORCHESTRATOR_NAME, "orchestrator_run_start", {
        "bots": list(BOT_REGISTRY.keys()),
        "ts": datetime.now(timezone.utc).isoformat(),
    })

    results = {}
    for bot_key in BOT_REGISTRY:
        results[bot_key] = run_bot(bot_key)

    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "bots_run": len(results),
        "ok": [k for k, v in results.items() if v["status"] == "ok"],
        "errors": [k for k, v in results.items() if v["status"] == "error"],
        "results": results,
    }

    log_event(ORCHESTRATOR_NAME, "orchestrator_run_complete", {
        "ok": len(summary["ok"]),
        "errors": len(summary["errors"]),
    })

    return summary


def print_status():
    """Print a summary of recent activity log entries."""
    entries = read_log(last_n=50)
    print(f"\n{'='*60}")
    print(f"SIG AGENT ACTIVITY LOG — last {len(entries)} entries")
    print(f"{'='*60}")
    for e in entries:
        level_marker = "⚠️ " if e["level"] == "WARN" else "🔴 " if e["level"] == "ERROR" else "   "
        print(f"{level_marker}[{e['ts'][:19]}] [{e['bot']:25s}] {e['action']}")
        if e.get("detail"):
            print(f"     {json.dumps(e['detail'])}")
    print()


def print_fees():
    """Print all pending x402 fee events."""
    fees = read_pending_fees()
    total = sum(f.get("fee_usd", 0) for f in fees)
    print(f"\n{'='*60}")
    print(f"PENDING x402 FEE LEDGER — {len(fees)} events — ${total:.4f} total")
    print(f"{'='*60}")
    for f in fees:
        print(f"  [{f['ts'][:19]}] {f['endpoint']:20s} ${f['fee_usd']:.4f}  ref={f['reference_id'][:8]}...")
    print(f"\nTotal pending: ${total:.4f} USDC")
    print(f"Wallet: {fees[0]['wallet'] if fees else 'N/A'}")
    print(f"Status: ALL PENDING — x402 not yet activated\n")


def main():
    parser = argparse.ArgumentParser(description="SIG Agent Orchestrator")
    parser.add_argument("--bot", choices=list(BOT_REGISTRY.keys()), help="Run a specific bot")
    parser.add_argument("--status", action="store_true", help="Print activity log summary")
    parser.add_argument("--fees", action="store_true", help="Print pending x402 fee ledger")
    args = parser.parse_args()

    if args.status:
        print_status()
    elif args.fees:
        print_fees()
    elif args.bot:
        result = run_bot(args.bot)
        print(json.dumps(result, indent=2, default=str))
    else:
        result = run_all()
        print(f"\n{'='*60}")
        print(f"ORCHESTRATOR COMPLETE — {datetime.now(timezone.utc).isoformat()[:19]}")
        print(f"{'='*60}")
        print(f"  Bots OK:     {len(result['ok'])}")
        print(f"  Bots failed: {len(result['errors'])}")
        if result["errors"]:
            print(f"  Errors: {result['errors']}")
        for bot_key, r in result["results"].items():
            status_icon = "✅" if r["status"] == "ok" else "❌"
            print(f"  {status_icon} {r['name']}")
        print()


if __name__ == "__main__":
    main()
