"""
bots/health_monitor.py
======================
Bot 3 — VPSBG Health Monitor Bot
Monitors CPU, RAM, disk, Docker containers.
Alerts on anomalies or resource pressure.
Tracks renewals, 2FA reminders, pending updates.
"""

import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

from shared.activity_log import log_event
from shared.aeo_schema import AGENT_STATE_DIR

BOT_NAME = "health_monitor"
STATE_FILE = Path(AGENT_STATE_DIR) / "health_monitor_state.json"

# Thresholds
THRESHOLDS = {
    "cpu_pct": 80.0,
    "ram_pct": 80.0,
    "disk_pct": 60.0,
    "container_restart_warn": 3,
}

# Known reminders
REMINDERS = [
    {
        "id": "vpsbg_renewal",
        "description": "VPSBG server auto-renews Feb 28 2026 — verify BoA card processed",
        "due_date": "2026-02-26",
        "priority": "HIGH",
    },
    {
        "id": "vpsbg_2fa",
        "description": "Enable 2FA on VPSBG account — previously failed, retry",
        "due_date": None,
        "priority": "MEDIUM",
    },
    {
        "id": "ubuntu_updates",
        "description": "47 Ubuntu updates applied Feb 22 2026 — monitor for new updates weekly",
        "due_date": "2026-03-01",
        "priority": "LOW",
    },
    {
        "id": "linkedin_premium_cancel",
        "description": "Cancel LinkedIn Premium by March 15 2026 if no leads convert",
        "due_date": "2026-03-15",
        "priority": "MEDIUM",
    },
    {
        "id": "psf_patent",
        "description": "File PSF provisional patent — discuss with Olayimika first",
        "due_date": None,
        "priority": "HIGH",
    },
    {
        "id": "midnight_nonprov",
        "description": "Midnight Compliance non-provisional due Nov 14 2026",
        "due_date": "2026-10-01",
        "priority": "HIGH",
    },
    {
        "id": "sig_nonprov",
        "description": "SIG non-provisional due Feb 15 2027",
        "due_date": "2027-01-01",
        "priority": "HIGH",
    },
]


def _run_cmd(cmd: str) -> tuple[int, str]:
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout.strip()
    except Exception as ex:
        return -1, str(ex)


def check_system() -> dict:
    """Check CPU, RAM, disk usage."""
    metrics = {}

    # CPU
    rc, out = _run_cmd("top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d'%' -f1")
    try:
        metrics["cpu_pct"] = float(out.split()[0]) if rc == 0 else None
    except Exception:
        # Try alternative
        rc2, out2 = _run_cmd("grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$4+$5)} END {print usage}'")
        try:
            metrics["cpu_pct"] = float(out2) if rc2 == 0 else None
        except Exception:
            metrics["cpu_pct"] = None

    # RAM
    rc, out = _run_cmd("free | grep Mem | awk '{print $3/$2 * 100.0}'")
    try:
        metrics["ram_pct"] = float(out) if rc == 0 else None
    except Exception:
        metrics["ram_pct"] = None

    # Disk
    rc, out = _run_cmd("df / | tail -1 | awk '{print $5}' | tr -d '%'")
    try:
        metrics["disk_pct"] = float(out) if rc == 0 else None
    except Exception:
        metrics["disk_pct"] = None

    return metrics


def check_containers() -> list:
    """Check Docker container states."""
    rc, out = _run_cmd("docker ps -a --format '{{.Names}}|{{.Status}}|{{.RunningFor}}'")
    containers = []
    if rc == 0:
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) >= 2:
                containers.append({
                    "name": parts[0],
                    "status": parts[1],
                    "running_for": parts[2] if len(parts) > 2 else "unknown",
                    "healthy": parts[1].startswith("Up"),
                })
    return containers


def check_sig_api() -> dict:
    """Ping SIG ingest API health endpoint."""
    rc, out = _run_cmd("curl -s --max-time 5 http://localhost:5010/health")
    if rc == 0 and out:
        try:
            return {"reachable": True, "response": json.loads(out)}
        except Exception:
            return {"reachable": True, "response": out}
    return {"reachable": False, "response": None}


def check_reminders() -> list:
    """Check which reminders are due or upcoming."""
    due = []
    today = datetime.now(timezone.utc).date()
    for r in REMINDERS:
        if r["due_date"]:
            due_date = datetime.strptime(r["due_date"], "%Y-%m-%d").date()
            days_until = (due_date - today).days
            if days_until <= 14:
                due.append({**r, "days_until": days_until})
        else:
            # No due date — include as standing reminder
            due.append({**r, "days_until": None})
    return due


def run() -> dict:
    """Main run loop for health monitor."""
    log_event(BOT_NAME, "run_start")
    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "alerts": [],
        "warnings": [],
        "system": {},
        "containers": [],
        "sig_api": {},
        "reminders": [],
    }

    # System metrics
    metrics = check_system()
    report["system"] = metrics

    for key, threshold in THRESHOLDS.items():
        if key in metrics and metrics[key] is not None:
            if metrics[key] >= threshold:
                msg = f"{key} at {metrics[key]:.1f}% — threshold {threshold}%"
                report["alerts"].append(msg)
                log_event(BOT_NAME, "threshold_breach", {"metric": key, "value": metrics[key]}, level="ERROR")
            elif metrics[key] >= threshold * 0.8:
                msg = f"{key} at {metrics[key]:.1f}% — approaching threshold"
                report["warnings"].append(msg)
                log_event(BOT_NAME, "threshold_warning", {"metric": key, "value": metrics[key]}, level="WARN")

    # Containers
    containers = check_containers()
    report["containers"] = containers
    for c in containers:
        if not c["healthy"]:
            report["alerts"].append(f"Container DOWN: {c['name']} — {c['status']}")
            log_event(BOT_NAME, "container_down", {"name": c["name"], "status": c["status"]}, level="ERROR")

    # SIG API
    sig_status = check_sig_api()
    report["sig_api"] = sig_status
    if not sig_status["reachable"]:
        report["alerts"].append("SIG Ingest API unreachable on port 5010")
        log_event(BOT_NAME, "api_unreachable", {}, level="ERROR")

    # Reminders
    reminders = check_reminders()
    report["reminders"] = reminders
    for r in reminders:
        if r.get("days_until") is not None and r["days_until"] <= 7:
            log_event(BOT_NAME, "reminder_urgent", {"id": r["id"], "days_until": r["days_until"]}, level="WARN")

    # Save state
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log_event(BOT_NAME, "run_complete", {
        "alerts": len(report["alerts"]),
        "warnings": len(report["warnings"]),
        "reminders_due": len(reminders),
    })

    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, default=str))
