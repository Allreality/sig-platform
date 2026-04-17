#!/usr/bin/env python3
"""
SIG Server Monitor — Total Reality Global
VPSBG (87.121.52.49) Health Agent with Claude AI Analysis + Discord Alerts
Runs via cron — recommended: every 15 minutes
"""

import os
import json
import socket
import subprocess
import datetime
import shutil
import glob
import requests
import anthropic

# ─────────────────────────────────────────
# CONFIGURATION — edit these
# ─────────────────────────────────────────

DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/1478336226355445933/ebs8tuSSZ6VdOrFzLJ0zEnYCwoKlRhGnOaMkRWqcuFFaefCZoYbLDpgOKLzjHbmoOO_d"
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")
LOG_FILE            = "/root/server-monitor/monitor.log"
ALERT_COOLDOWN_FILE = "/root/server-monitor/last_alert.json"
ALERT_COOLDOWN_MINS = 30   # Don't re-alert same issue within 30 min

# Ports to check (name → port)
SERVICES = {
    "SIG Ingest API":        5010,
}

# Thresholds
DISK_WARN_PCT   = 80
MEMORY_WARN_PCT = 85
CPU_WARN_PCT    = 90

# Attestation report check
ATTESTATION_DIR = "/root/attestation-reports/"


# ─────────────────────────────────────────
# CHECKS
# ─────────────────────────────────────────

def check_ports() -> dict:
    results = {}
    for name, port in SERVICES.items():
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex(("127.0.0.1", port))
        sock.close()
        results[name] = "UP" if result == 0 else "DOWN"
    return results


def check_disk() -> dict:
    usage = shutil.disk_usage("/")
    pct = (usage.used / usage.total) * 100
    return {
        "total_gb":    round(usage.total / 1e9, 1),
        "used_gb":     round(usage.used  / 1e9, 1),
        "free_gb":     round(usage.free  / 1e9, 1),
        "percent_used": round(pct, 1),
        "status":      "WARN" if pct >= DISK_WARN_PCT else "OK"
    }


def check_memory() -> dict:
    try:
        with open("/proc/meminfo") as f:
            info = {}
            for line in f:
                parts = line.split()
                info[parts[0].rstrip(":")] = int(parts[1])
        total = info.get("MemTotal", 1)
        avail = info.get("MemAvailable", total)
        used_pct = ((total - avail) / total) * 100
        return {
            "total_mb":     round(total  / 1024, 1),
            "available_mb": round(avail  / 1024, 1),
            "percent_used": round(used_pct, 1),
            "status":       "WARN" if used_pct >= MEMORY_WARN_PCT else "OK"
        }
    except Exception as e:
        return {"error": str(e), "status": "UNKNOWN"}


def check_cpu() -> dict:
    try:
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        pct = (load1 / cpu_count) * 100
        return {
            "load_1m":      round(load1, 2),
            "load_5m":      round(load5, 2),
            "load_15m":     round(load15, 2),
            "cpu_count":    cpu_count,
            "percent_used": round(pct, 1),
            "status":       "WARN" if pct >= CPU_WARN_PCT else "OK"
        }
    except Exception as e:
        return {"error": str(e), "status": "UNKNOWN"}


def check_attestation() -> dict:
    if not os.path.exists(ATTESTATION_DIR):
        return {"status": "MISSING_DIR", "message": f"{ATTESTATION_DIR} not found"}

    reports = sorted(glob.glob(os.path.join(ATTESTATION_DIR, "*.json")) +
                     glob.glob(os.path.join(ATTESTATION_DIR, "*.txt")))
    if not reports:
        return {"status": "NO_REPORTS", "message": "No attestation reports found"}

    latest      = reports[-1]
    modified_ts = os.path.getmtime(latest)
    modified_dt = datetime.datetime.fromtimestamp(modified_ts)
    age_hours   = (datetime.datetime.now() - modified_dt).total_seconds() / 3600

    return {
        "latest_report": os.path.basename(latest),
        "last_modified": modified_dt.strftime("%Y-%m-%d %H:%M UTC"),
        "age_hours":     round(age_hours, 1),
        "status":        "WARN" if age_hours > 26 else "OK",   # allow 2hr window past 24h
        "message":       f"Report is {round(age_hours,1)}h old" if age_hours > 26 else "Fresh"
    }


def collect_system_snapshot() -> dict:
    return {
        "timestamp":    datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "hostname":     socket.gethostname(),
        "ports":        check_ports(),
        "disk":         check_disk(),
        "memory":       check_memory(),
        "cpu":          check_cpu(),
        "attestation":  check_attestation(),
    }


# ─────────────────────────────────────────
# CLAUDE ANALYSIS
# ─────────────────────────────────────────

def analyze_with_claude(snapshot: dict) -> str:
    if not ANTHROPIC_API_KEY:
        return "⚠️ No ANTHROPIC_API_KEY — skipping AI analysis."

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""You are a server monitoring agent for Total Reality Global's VPSBG server (87.121.52.49).
This server runs the Signal Intelligence Grid (SIG), Midnight Infrastructure, and AMD EPYC SEV-SNP attestation.

Analyze this health snapshot and provide a concise report:

{json.dumps(snapshot, indent=2)}

Respond with:
1. Overall status: 🟢 HEALTHY / 🟡 WARNING / 🔴 CRITICAL
2. Key issues found (if any) — be specific
3. Recommended action (1-2 sentences max)
4. Any patterns worth noting

Be direct. No fluff. This goes to a Discord channel."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )
    return message.content[0].text


# ─────────────────────────────────────────
# ALERT LOGIC
# ─────────────────────────────────────────

def has_issues(snapshot: dict) -> bool:
    """Return True if any check is not OK/UP."""
    ports_down = [k for k, v in snapshot["ports"].items() if v == "DOWN"]
    disk_warn  = snapshot["disk"].get("status") == "WARN"
    mem_warn   = snapshot["memory"].get("status") == "WARN"
    cpu_warn   = snapshot["cpu"].get("status") == "WARN"
    att_warn   = snapshot["attestation"].get("status") not in ("OK",)
    return bool(ports_down or disk_warn or mem_warn or cpu_warn or att_warn)


def cooldown_active(issue_key: str) -> bool:
    """Prevent alert spam for the same issue."""
    if not os.path.exists(ALERT_COOLDOWN_FILE):
        return False
    try:
        with open(ALERT_COOLDOWN_FILE) as f:
            data = json.load(f)
        last = data.get(issue_key)
        if not last:
            return False
        last_dt = datetime.datetime.fromisoformat(last)
        return (datetime.datetime.utcnow() - last_dt).total_seconds() < ALERT_COOLDOWN_MINS * 60
    except Exception:
        return False


def update_cooldown(issue_key: str):
    data = {}
    if os.path.exists(ALERT_COOLDOWN_FILE):
        try:
            with open(ALERT_COOLDOWN_FILE) as f:
                data = json.load(f)
        except Exception:
            pass
    data[issue_key] = datetime.datetime.utcnow().isoformat()
    os.makedirs(os.path.dirname(ALERT_COOLDOWN_FILE), exist_ok=True)
    with open(ALERT_COOLDOWN_FILE, "w") as f:
        json.dump(data, f)


# ─────────────────────────────────────────
# DISCORD
# ─────────────────────────────────────────

def send_discord(title: str, analysis: str, snapshot: dict, color: int = 0xFF0000):
    """Send rich embed to Discord."""
    if DISCORD_WEBHOOK_URL == "YOUR_DISCORD_WEBHOOK_URL_HERE":
        print("[Discord] Webhook not configured — printing to stdout instead.")
        print(f"\n{'='*60}\n{title}\n{analysis}\n{'='*60}\n")
        return

    ports_down = [k for k, v in snapshot["ports"].items() if v == "DOWN"]
    ports_up   = [k for k, v in snapshot["ports"].items() if v == "UP"]

    fields = [
        {"name": "🖥️ Host",       "value": snapshot["hostname"],                       "inline": True},
        {"name": "🕐 Time (UTC)", "value": snapshot["timestamp"],                       "inline": True},
        {"name": "💾 Disk",       "value": f"{snapshot['disk']['percent_used']}% used", "inline": True},
        {"name": "🧠 Memory",     "value": f"{snapshot['memory'].get('percent_used','?')}% used", "inline": True},
        {"name": "⚡ CPU Load",   "value": f"{snapshot['cpu'].get('load_1m','?')} (1m)", "inline": True},
        {"name": "📋 Attestation","value": snapshot['attestation'].get('message','?'),  "inline": True},
        {"name": "✅ Services UP", "value": "\n".join(ports_up) or "None",              "inline": True},
    ]
    if ports_down:
        fields.append({"name": "❌ Services DOWN", "value": "\n".join(ports_down), "inline": True})

    payload = {
        "username": "SIG Monitor",
        "avatar_url": "https://img.icons8.com/color/96/server.png",
        "embeds": [{
            "title":       title,
            "description": analysis,
            "color":       color,
            "fields":      fields,
            "footer":      {"text": "Total Reality Global — VPSBG Monitor"},
            "timestamp":   datetime.datetime.utcnow().isoformat()
        }]
    }

    try:
        r = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        r.raise_for_status()
        print(f"[Discord] Alert sent — status {r.status_code}")
    except Exception as e:
        print(f"[Discord] Failed to send: {e}")


# ─────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────

def log_run(snapshot: dict, analysis: str, alerted: bool):
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    entry = {
        "timestamp":  snapshot["timestamp"],
        "alerted":    alerted,
        "ports_down": [k for k, v in snapshot["ports"].items() if v == "DOWN"],
        "disk_pct":   snapshot["disk"].get("percent_used"),
        "mem_pct":    snapshot["memory"].get("percent_used"),
        "cpu_load":   snapshot["cpu"].get("load_1m"),
        "attestation":snapshot["attestation"].get("status"),
        "analysis":   analysis[:200]
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ─────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────

def main():
    print(f"[{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}] Running SIG Server Monitor...")

    snapshot = collect_system_snapshot()
    issues   = has_issues(snapshot)
    analysis = analyze_with_claude(snapshot)

    alerted = False

    if issues:
        issue_key = "general"  # Could be made more granular per issue type
        if not cooldown_active(issue_key):
            send_discord(
                title  = "🔴 VPSBG Server Alert — Action Required",
                analysis = analysis,
                snapshot = snapshot,
                color  = 0xFF4444
            )
            update_cooldown(issue_key)
            alerted = True
        else:
            print("[Cooldown] Issue known — skipping repeat alert.")
    else:
        # Optionally send a daily heartbeat (once per day)
        now = datetime.datetime.utcnow()
        if now.hour == 7 and now.minute < 15:  # ~7 AM UTC daily heartbeat
            send_discord(
                title    = "🟢 VPSBG Daily Heartbeat — All Systems Nominal",
                analysis = analysis,
                snapshot = snapshot,
                color    = 0x00CC66
            )
            alerted = True

    log_run(snapshot, analysis, alerted)
    print(f"[Done] Issues: {issues} | Alerted: {alerted}")
    print(f"[Claude] {analysis[:120]}...")


if __name__ == "__main__":
    main()
