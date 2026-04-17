"""
bots/r2_telemetry.py
====================
Bot 7 — R2 Telemetry Bot
Handles raw telemetry offload to Cloudflare R2.
Operates in STAGING mode until R2 is configured.
Maintains evidence continuity and logs all transfers.
"""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from shared.activity_log import log_event
from shared.aeo_schema import OFFCHAIN_DIR, EVIDENCE_DIR, AGENT_STATE_DIR

BOT_NAME = "r2_telemetry"
STATE_FILE = Path(AGENT_STATE_DIR) / "r2_telemetry_state.json"
TRANSFER_LOG = Path("/var/sig/agents/r2_transfer_log.jsonl")

# R2 configuration — populate when Cloudflare R2 is configured
R2_CONFIG = {
    "enabled": os.environ.get("R2_ENABLED", "false").lower() == "true",
    "account_id": os.environ.get("R2_ACCOUNT_ID"),
    "bucket_name": os.environ.get("R2_BUCKET_NAME", "sig-telemetry"),
    "access_key_id": os.environ.get("R2_ACCESS_KEY_ID"),
    "secret_access_key": os.environ.get("R2_SECRET_ACCESS_KEY"),
    "endpoint_url": os.environ.get("R2_ENDPOINT_URL"),
}

# Local staging directory — holds files pending R2 upload
STAGING_DIR = Path("/var/sig/r2-staging")
ARCHIVE_DIR = Path("/var/sig/r2-archive")


def _load_state() -> dict:
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "r2_enabled": False,
        "total_files_staged": 0,
        "total_files_uploaded": 0,
        "total_bytes_moved": 0,
        "last_run": None,
    }


def _save_state(state: dict):
    Path(AGENT_STATE_DIR).mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _log_transfer(file_path: str, destination: str, status: str, bytes_moved: int = 0):
    """Append one transfer record to the transfer log."""
    TRANSFER_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "file": file_path,
        "destination": destination,
        "status": status,
        "bytes_moved": bytes_moved,
    }
    with open(TRANSFER_LOG, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def _collect_telemetry_files() -> list:
    """
    Collect raw telemetry files from offchain storage.
    Returns list of Path objects ready for staging/upload.
    """
    files = []
    for source_dir in [Path(OFFCHAIN_DIR), Path(EVIDENCE_DIR)]:
        if source_dir.exists():
            for f in source_dir.glob("*.json"):
                files.append(f)
    return files


def _stage_file(file_path: Path) -> dict:
    """
    Copy file to staging directory.
    Staging holds files until R2 is activated.
    """
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    dest = STAGING_DIR / file_path.name
    if not dest.exists():
        shutil.copy2(file_path, dest)
        size = dest.stat().st_size
        log_event(BOT_NAME, "file_staged", {"file": file_path.name, "bytes": size})
        return _log_transfer(str(file_path), str(dest), "staged", size)
    return _log_transfer(str(file_path), str(dest), "already_staged", 0)


def _upload_to_r2(file_path: Path) -> dict:
    """
    Upload file to Cloudflare R2.
    Only called when R2_ENABLED=true and credentials are set.
    """
    if not R2_CONFIG["enabled"]:
        return {"status": "r2_disabled"}

    try:
        import boto3
        from botocore.config import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=R2_CONFIG["endpoint_url"],
            aws_access_key_id=R2_CONFIG["access_key_id"],
            aws_secret_access_key=R2_CONFIG["secret_access_key"],
            config=Config(signature_version="s3v4"),
        )

        key = f"telemetry/{datetime.now(timezone.utc).strftime('%Y/%m/%d')}/{file_path.name}"
        size = file_path.stat().st_size

        s3.upload_file(str(file_path), R2_CONFIG["bucket_name"], key)

        # Move to archive after successful upload
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(file_path), ARCHIVE_DIR / file_path.name)

        log_event(BOT_NAME, "file_uploaded_r2", {
            "file": file_path.name,
            "key": key,
            "bytes": size,
        })
        return _log_transfer(str(file_path), f"r2://{R2_CONFIG['bucket_name']}/{key}", "uploaded", size)

    except Exception as ex:
        log_event(BOT_NAME, "r2_upload_error", {"file": file_path.name, "error": str(ex)}, level="ERROR")
        return _log_transfer(str(file_path), "r2://error", "failed", 0)


def get_storage_pressure() -> dict:
    """Check current VPS storage usage."""
    try:
        import shutil as sh
        total, used, free = sh.disk_usage("/")
        pct_used = round((used / total) * 100, 1)
        staging_size = sum(f.stat().st_size for f in STAGING_DIR.glob("*") if STAGING_DIR.exists() and f.is_file())
        return {
            "disk_total_gb": round(total / 1e9, 2),
            "disk_used_gb": round(used / 1e9, 2),
            "disk_free_gb": round(free / 1e9, 2),
            "disk_pct_used": pct_used,
            "staging_files": len(list(STAGING_DIR.glob("*"))) if STAGING_DIR.exists() else 0,
            "staging_size_mb": round(staging_size / 1e6, 2),
        }
    except Exception as ex:
        return {"error": str(ex)}


def run() -> dict:
    """
    Main run loop.
    - If R2 disabled: stage files locally, report storage pressure
    - If R2 enabled: upload staged files to R2
    """
    log_event(BOT_NAME, "run_start", {"r2_enabled": R2_CONFIG["enabled"]})
    state = _load_state()

    files = _collect_telemetry_files()
    staged = []
    uploaded = []
    errors = []

    for f in files:
        if R2_CONFIG["enabled"]:
            result = _upload_to_r2(f)
            if result.get("status") == "uploaded":
                uploaded.append(f.name)
                state["total_files_uploaded"] += 1
                state["total_bytes_moved"] += result.get("bytes_moved", 0)
            else:
                errors.append(f.name)
        else:
            result = _stage_file(f)
            staged.append(f.name)
            state["total_files_staged"] += 1

    storage = get_storage_pressure()
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["r2_enabled"] = R2_CONFIG["enabled"]
    _save_state(state)

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "r2_enabled": R2_CONFIG["enabled"],
        "mode": "upload" if R2_CONFIG["enabled"] else "staging",
        "files_found": len(files),
        "files_staged": len(staged),
        "files_uploaded": len(uploaded),
        "errors": errors,
        "storage": storage,
        "activation_note": (
            "R2 is DISABLED. Files are being staged locally at /var/sig/r2-staging/. "
            "To activate: set R2_ENABLED=true and configure R2_ACCOUNT_ID, "
            "R2_BUCKET_NAME, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ENDPOINT_URL "
            "in the .env file."
        ) if not R2_CONFIG["enabled"] else "R2 active — uploads in progress.",
    }

    if storage.get("disk_pct_used", 0) >= 60:
        log_event(BOT_NAME, "storage_pressure", storage, level="WARN")

    log_event(BOT_NAME, "run_complete", {
        "files_processed": len(files),
        "mode": report["mode"],
    })

    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
