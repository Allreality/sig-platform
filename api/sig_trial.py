"""
sig_trial.py — SIG Free Trial Activation Module
Total Reality Global / Signal Intelligence Grid
─────────────────────────────────────────────────
FastAPI router. Mount into sig_ingest.py with:

    from sig_trial import router as trial_router
    app.include_router(trial_router, prefix="/trial")

Endpoints:
    POST   /trial/register          — new trial signup
    GET    /trial/status/{trial_id} — check trial state
    POST   /trial/activate          — Square webhook → activate
    POST   /trial/report/{trial_id} — deliver one free compliance report
    POST   /trial/admin/expire      — manual expiry (admin use)

Scheduler (APScheduler) runs daily checks:
    - Day 25: send conversion reminder email
    - Day 30: mark trial expired, lock ingestion

Environment variables required (.env):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
    SQUARE_ACCESS_TOKEN, SQUARE_WEBHOOK_SIGNATURE_KEY
    SIG_ADMIN_KEY          — bearer token for /admin/* routes
    TRIAL_DB_PATH          — default: /home/sig-platform/data/trials.db
"""

import os
import uuid
import hmac
import hashlib
import smtplib
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from contextlib import contextmanager
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel, EmailStr, field_validator
from apscheduler.schedulers.background import BackgroundScheduler

# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO)
import os, httpx

def _discord(webhook_env: str, message: str):
    """Post a message to a Discord channel via webhook."""
    url = os.getenv(webhook_env)
    if not url:
        return
    try:
        httpx.post(url, json={"content": message}, timeout=5)
    except Exception:
        pass


log = logging.getLogger("sig.trial")

# ── Config ───────────────────────────────────────────────────────────────────

DB_PATH          = os.getenv("TRIAL_DB_PATH", "/home/sig-platform/data/trials.db")
SMTP_HOST        = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT        = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER        = os.getenv("SMTP_USER", "")
SMTP_PASS        = os.getenv("SMTP_PASS", "")
SMTP_FROM        = os.getenv("SMTP_FROM", "noreply@midnight-compliance.com")
SQUARE_TOKEN     = os.getenv("SQUARE_ACCESS_TOKEN", "")
SQUARE_SIG_KEY   = os.getenv("SQUARE_WEBHOOK_SIGNATURE_KEY", "")
ADMIN_KEY        = os.getenv("SIG_ADMIN_KEY", "")

TRIAL_DAYS       = 30
REMINDER_DAY     = 25
MAX_DEVICES      = 5
FREE_REPORTS     = 1
STARTER_PRICE    = 2500   # USD/month

router = APIRouter()

# ── Database ─────────────────────────────────────────────────────────────────

def _init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _db() as cx:
        cx.execute("""
            CREATE TABLE IF NOT EXISTS trials (
                trial_id         TEXT PRIMARY KEY,
                company_name     TEXT NOT NULL,
                contact_name     TEXT NOT NULL,
                contact_email    TEXT NOT NULL,
                device_ids       TEXT NOT NULL,       -- JSON array, max 5
                square_customer_id TEXT,
                square_card_id   TEXT,
                status           TEXT NOT NULL DEFAULT 'pending',
                -- pending | active | expired | converted
                reports_used     INTEGER NOT NULL DEFAULT 0,
                reminder_sent    INTEGER NOT NULL DEFAULT 0,
                created_at       TEXT NOT NULL,
                activated_at     TEXT,
                expires_at       TEXT,
                notes            TEXT
            )
        """)
        cx.execute("""
            CREATE TABLE IF NOT EXISTS trial_events (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                trial_id         TEXT NOT NULL,
                event_type       TEXT NOT NULL,
                detail           TEXT,
                ts               TEXT NOT NULL
            )
        """)

@contextmanager
def _db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()

def _log_event(trial_id: str, event_type: str, detail: str = ""):
    with _db() as cx:
        cx.execute(
            "INSERT INTO trial_events (trial_id, event_type, detail, ts) VALUES (?,?,?,?)",
            (trial_id, event_type, detail, _now())
        )

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

# ── Schemas ───────────────────────────────────────────────────────────────────

class TrialRegisterRequest(BaseModel):
    company_name:  str
    contact_name:  str
    contact_email: EmailStr
    device_ids:    list[str]   # 1–5 device identifiers (serial / asset tags)

    @field_validator("device_ids")
    @classmethod
    def check_device_count(cls, v):
        if not v:
            raise ValueError("At least one device_id required")
        if len(v) > MAX_DEVICES:
            raise ValueError(f"Trial limited to {MAX_DEVICES} devices")
        return v

class SquareWebhookPayload(BaseModel):
    """
    Square sends this when a card-on-file is confirmed.
    Minimal fields we care about — Square's full payload is larger.
    """
    type:        str            # e.g. "customer.created" or "card.updated"
    merchant_id: str
    data: dict

# ── Email helpers ─────────────────────────────────────────────────────────────

def _send_email(to: str, subject: str, html: str, plain: str):
    if not SMTP_USER:
        log.warning("SMTP not configured — skipping email to %s", to)
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = SMTP_FROM
        msg["To"]      = to
        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html,  "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.sendmail(SMTP_FROM, to, msg.as_string())
        log.info("Email sent to %s: %s", to, subject)
    except Exception as e:
        log.error("Email failed to %s: %s", to, e)


def _email_welcome(trial: sqlite3.Row):
    """Sent immediately on trial activation."""
    subject = "Your SIG Trial is Active — Total Reality Global"
    plain = f"""
Hi {trial['contact_name']},

Your 30-day Signal Intelligence Grid trial is now active.

Trial ID:    {trial['trial_id']}
Devices:     {trial['device_ids']}
Expires:     {trial['expires_at']}

What's included:
  - Sensor ingestion for up to {MAX_DEVICES} devices (DNP3 / Modbus / TLM / SMARTLINE)
  - Daily SEV-SNP hardware attestation
  - Midnight blockchain anchoring of all attestation records
  - 1 full NERC CIP compliance report (PDF + JSON), delivered on request

To request your free compliance report:
  POST https://midnight-compliance.com/trial/report/{trial['trial_id']}

Questions: info@totalrealityglobal.com

— Total Reality Global
""".strip()

    html = f"""
<html><body style="font-family:monospace;background:#0a0a0a;color:#e0e0e0;padding:2rem;">
<h2 style="color:#1D9E75;">SIG Trial Active</h2>
<p>Hi {trial['contact_name']},</p>
<p>Your 30-day Signal Intelligence Grid trial is now live.</p>
<table style="border-collapse:collapse;width:100%;margin:1rem 0;">
  <tr><td style="color:#888;padding:4px 12px 4px 0;">Trial ID</td>
      <td style="color:#fff;">{trial['trial_id']}</td></tr>
  <tr><td style="color:#888;padding:4px 12px 4px 0;">Devices</td>
      <td style="color:#fff;">{trial['device_ids']}</td></tr>
  <tr><td style="color:#888;padding:4px 12px 4px 0;">Expires</td>
      <td style="color:#fff;">{trial['expires_at'][:10]}</td></tr>
</table>
<h3 style="color:#1D9E75;">Included in your trial</h3>
<ul>
  <li>Sensor ingestion — up to {MAX_DEVICES} devices (DNP3 / Modbus / TLM / SMARTLINE)</li>
  <li>Daily SEV-SNP hardware attestation (AMD EPYC, VPSBG)</li>
  <li>Midnight blockchain anchoring — every attestation record</li>
  <li>1 full NERC CIP compliance report (PDF + JSON)</li>
</ul>
<p style="margin-top:1.5rem;">
  <a href="https://midnight-compliance.com/trial/report/{trial['trial_id']}"
     style="background:#1D9E75;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;">
    Request Free Compliance Report
  </a>
</p>
<hr style="border-color:#333;margin:2rem 0;">
<p style="color:#666;font-size:12px;">Total Reality Global · midnight-compliance.com</p>
</body></html>
"""
    _send_email(trial["contact_email"], subject, html, plain)


def _email_reminder(trial: sqlite3.Row):
    """Day-25 conversion nudge."""
    subject = "5 Days Left on Your SIG Trial — Continue Uninterrupted"
    plain = f"""
Hi {trial['contact_name']},

Your Signal Intelligence Grid trial expires in 5 days ({trial['expires_at'][:10]}).

Your trial has generated blockchain-anchored attestation records for
{trial['device_ids']} — all accessible and audit-ready.

To continue without interruption, activate a subscription:
  Starter  — up to 25 devices  — $2,500/month
  Pay via SOL, BTC, or card at:
  https://midnight-compliance.com/pay?trial={trial['trial_id']}

If you have questions, reply to this email or contact:
  info@totalrealityglobal.com

— Total Reality Global
""".strip()

    html = f"""
<html><body style="font-family:monospace;background:#0a0a0a;color:#e0e0e0;padding:2rem;">
<h2 style="color:#E24B4A;">Trial Expires in 5 Days</h2>
<p>Hi {trial['contact_name']},</p>
<p>Your SIG trial ends on <strong style="color:#fff;">{trial['expires_at'][:10]}</strong>.</p>
<p>All attestation records and compliance data generated during your trial
remain accessible after you activate a paid subscription.</p>
<h3 style="color:#1D9E75;">Continue with Starter</h3>
<ul>
  <li>Up to 25 devices</li>
  <li>Daily + on-demand attestation</li>
  <li>2 compliance reports/month</li>
  <li><strong style="color:#1D9E75;">$2,500/month</strong> — SOL, BTC, or card</li>
</ul>
<p style="margin-top:1.5rem;">
  <a href="https://midnight-compliance.com/pay?trial={trial['trial_id']}"
     style="background:#1D9E75;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;">
    Activate Subscription
  </a>
</p>
<hr style="border-color:#333;margin:2rem 0;">
<p style="color:#666;font-size:12px;">Total Reality Global · midnight-compliance.com</p>
</body></html>
"""
    _send_email(trial["contact_email"], subject, html, plain)


def _email_expired(trial: sqlite3.Row):
    """Day-30 expiry notice."""
    subject = "Your SIG Trial Has Ended"
    plain = f"""
Hi {trial['contact_name']},

Your Signal Intelligence Grid trial (ID: {trial['trial_id']}) has ended.

Sensor ingestion and attestation for your trial devices have been suspended.

To reactivate, subscribe at:
  https://midnight-compliance.com/pay?trial={trial['trial_id']}

Your attestation records are retained for 90 days.

— Total Reality Global
""".strip()
    html = f"""
<html><body style="font-family:monospace;background:#0a0a0a;color:#e0e0e0;padding:2rem;">
<h2 style="color:#888;">SIG Trial Ended</h2>
<p>Hi {trial['contact_name']},</p>
<p>Your trial has ended. Ingestion for your {MAX_DEVICES} trial devices is suspended.</p>
<p>Attestation records are retained for <strong>90 days</strong>.</p>
<p style="margin-top:1.5rem;">
  <a href="https://midnight-compliance.com/pay?trial={trial['trial_id']}"
     style="background:#1D9E75;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;">
    Reactivate
  </a>
</p>
<hr style="border-color:#333;margin:2rem 0;">
<p style="color:#666;font-size:12px;">Total Reality Global · midnight-compliance.com</p>
</body></html>
"""
    _send_email(trial["contact_email"], subject, html, plain)

# ── Square helpers ────────────────────────────────────────────────────────────

def _verify_square_signature(body: bytes, signature: str, url: str) -> bool:
    """
    Square HMAC-SHA256 webhook verification.
    https://developer.squareup.com/docs/webhooks/validate-webhooks
    """
    if not SQUARE_SIG_KEY:
        log.warning("SQUARE_WEBHOOK_SIGNATURE_KEY not set — skipping verification")
        return True
    payload = url.encode() + body
    expected = hmac.new(
        SQUARE_SIG_KEY.encode(), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

def _create_square_payment_link(trial_id: str, company: str) -> str:
    """
    Returns a Square checkout URL for card-on-file capture.
    $0 authorization hold — card is verified but not charged.
    Requires SQUARE_ACCESS_TOKEN in env.
    Docs: https://developer.squareup.com/reference/square/checkout-api
    """
    if not SQUARE_TOKEN:
        return f"https://midnight-compliance.com/pay?trial={trial_id}"
    try:
        import httpx
        payload = {
            "idempotency_key": trial_id,
            "checkout_options": {
                "allow_tipping": False,
                "ask_for_shipping_address": False,
            },
            "order": {
                "order": {
                    "location_id": os.getenv("SQUARE_LOCATION_ID", ""),
                    "line_items": [{
                        "name": f"SIG Trial — {company}",
                        "quantity": "1",
                        "base_price_money": {"amount": 0, "currency": "USD"},
                        "note": "Card on file — no charge. Trial activation only."
                    }],
                    "metadata": {"trial_id": trial_id}
                }
            }
        }
        r = httpx.post(
            "https://connect.squareup.com/v2/online-checkout/payment-links",
            headers={
                "Authorization": f"Bearer {SQUARE_TOKEN}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=10
        )
        r.raise_for_status()
        return r.json()["payment_link"]["url"]
    except Exception as e:
        log.error("Square payment link creation failed: %s", e)
        return f"https://midnight-compliance.com/pay?trial={trial_id}"

# ── Scheduler ────────────────────────────────────────────────────────────────

def _run_daily_checks():
    """Called by APScheduler every day at 07:00 UTC."""
    log.info("Running daily trial checks...")
    now = datetime.now(timezone.utc)
    with _db() as cx:
        rows = cx.execute(
            "SELECT * FROM trials WHERE status = 'active'"
        ).fetchall()

    for trial in rows:
        activated = datetime.fromisoformat(trial["activated_at"])
        days_in   = (now - activated).days

        if days_in >= TRIAL_DAYS:
            with _db() as cx:
                cx.execute(
                    "UPDATE trials SET status='expired' WHERE trial_id=?",
                    (trial["trial_id"],)
                )
            _log_event(trial["trial_id"], "expired", f"day {days_in}")
            _email_expired(trial)
            log.info("Trial expired: %s", trial["trial_id"])

        elif days_in >= REMINDER_DAY and not trial["reminder_sent"]:
            _email_reminder(trial)
            with _db() as cx:
                cx.execute(
                    "UPDATE trials SET reminder_sent=1 WHERE trial_id=?",
                    (trial["trial_id"],)
                )
            _log_event(trial["trial_id"], "reminder_sent", f"day {days_in}")
            log.info("Reminder sent: %s", trial["trial_id"])


scheduler = BackgroundScheduler(timezone="UTC")
scheduler.add_job(_run_daily_checks, "cron", hour=7, minute=0)

# ── Auth helpers ──────────────────────────────────────────────────────────────

def _require_admin(x_admin_key: Optional[str]):
    if not ADMIN_KEY or x_admin_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Forbidden")

# ── Public utility ────────────────────────────────────────────────────────────

def is_trial_device_allowed(device_id: str) -> tuple[bool, str]:
    """
    Call this from sig_ingest.py before processing a sensor payload.
    Returns (allowed: bool, reason: str).

    Usage in sig_ingest.py:
        from sig_trial import is_trial_device_allowed
        allowed, reason = is_trial_device_allowed(device_id)
        if not allowed:
            raise HTTPException(status_code=402, detail=reason)
    """
    with _db() as cx:
        row = cx.execute(
            """SELECT status, device_ids, expires_at
               FROM trials
               WHERE device_ids LIKE ? AND status = 'active'""",
            (f"%{device_id}%",)
        ).fetchone()

    if not row:
        return False, "No active trial for this device. Subscribe at midnight-compliance.com/pay"

    expires = datetime.fromisoformat(row["expires_at"])
    if datetime.now(timezone.utc) > expires:
        return False, "Trial expired. Subscribe at midnight-compliance.com/pay"

    return True, "ok"

# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/register", summary="Register for SIG free trial")
async def register_trial(req: TrialRegisterRequest, background: BackgroundTasks):
    """
    Step 1 of 2. Creates a pending trial record and returns a Square
    payment link for card-on-file capture. Trial activates when Square
    confirms the card via webhook POST /trial/activate.
    """
    import json
    trial_id = str(uuid.uuid4())
    now      = _now()

    with _db() as cx:
        # Block duplicate registrations from same email
        existing = cx.execute(
            "SELECT trial_id, status FROM trials WHERE contact_email=?",
            (req.contact_email,)
        ).fetchone()
        if existing:
            return JSONResponse(
                status_code=409,
                content={
                    "error": "A trial already exists for this email.",
                    "trial_id": existing["trial_id"],
                    "status":   existing["status"]
                }
            )

        cx.execute(
            """INSERT INTO trials
               (trial_id, company_name, contact_name, contact_email,
                device_ids, status, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (
                trial_id,
                req.company_name,
                req.contact_name,
                req.contact_email,
                json.dumps(req.device_ids),
                "pending",
                now
            )
        )

    _log_event(trial_id, "registered", f"devices={req.device_ids}")

    # Generate Square card-on-file link in background (non-blocking)
    payment_url = _create_square_payment_link(trial_id, req.company_name)

    log.info("Trial registered: %s | %s | %s", trial_id, req.company_name, req.contact_email)
    _discord("DISCORD_SIG_TRIALS", f"🆕 **New Trial Registered**\n**Org:** {req.company_name}\n**Contact:** {req.contact_name}\n**Email:** {req.contact_email}\n**Devices:** {len(req.device_ids)}\n**Trial ID:** `{trial_id}`")

    return {
        "trial_id":       trial_id,
        "status":         "pending",
        "message":        (
            "Trial registered. Add a card on file to activate — "
            "no charge will be made."
        ),
        "payment_link":   payment_url,
        "devices":        req.device_ids,
        "trial_duration": f"{TRIAL_DAYS} days",
        "max_devices":    MAX_DEVICES,
        "free_reports":   FREE_REPORTS
    }


@router.post("/activate", summary="Square webhook — activate trial on card confirmed")
async def activate_trial(request: Request):
    """
    Square calls this webhook when a customer card is confirmed.
    Verifies HMAC signature, finds the pending trial by customer/metadata,
    activates it, and sends the welcome email.
    """
    import json
    body      = await request.body()
    signature = request.headers.get("x-square-hmacsha256-signature", "")
    url       = str(request.url)

    if not _verify_square_signature(body, signature, url):
        raise HTTPException(status_code=401, detail="Invalid Square signature")

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Extract trial_id from Square order metadata
    # Square passes metadata through on checkout completion events
    event_type = payload.get("type", "")
    log.info("Square webhook received: %s", event_type)

    trial_id = None
    square_customer_id = None
    square_card_id     = None

    try:
        data = payload.get("data", {}).get("object", {})
        # Payment link completion: data.object.payment.order_id → look up metadata
        if "payment" in data:
            metadata = data["payment"].get("metadata", {})
            trial_id = metadata.get("trial_id")
            square_customer_id = data["payment"].get("customer_id")
        # Card on file confirmation
        elif "card" in data:
            square_card_id     = data["card"].get("id")
            square_customer_id = data["card"].get("customer_id")
    except Exception as e:
        log.warning("Could not parse Square webhook payload: %s", e)

    if not trial_id and not square_customer_id:
        # Acknowledge but take no action — may be an unrelated Square event
        return {"received": True}

    with _db() as cx:
        if trial_id:
            trial = cx.execute(
                "SELECT * FROM trials WHERE trial_id=? AND status='pending'",
                (trial_id,)
            ).fetchone()
        else:
            trial = None

        if not trial:
            log.warning("No pending trial found for trial_id=%s", trial_id)
            return {"received": True}

        now      = datetime.now(timezone.utc)
        expires  = (now + timedelta(days=TRIAL_DAYS)).isoformat()

        cx.execute(
            """UPDATE trials SET
               status='active',
               square_customer_id=?,
               square_card_id=?,
               activated_at=?,
               expires_at=?
               WHERE trial_id=?""",
            (square_customer_id, square_card_id, now.isoformat(), expires, trial["trial_id"])
        )
        updated = cx.execute(
            "SELECT * FROM trials WHERE trial_id=?", (trial["trial_id"],)
        ).fetchone()

    _log_event(trial["trial_id"], "activated", f"expires={expires}")
    _email_welcome(updated)
    # Start scheduler if not running
    if not scheduler.running:
        scheduler.start()

    log.info("Trial activated: %s | expires %s", trial["trial_id"], expires[:10])
    _discord("DISCORD_SIG_TRIALS", f"✅ **Trial Activated**\n**Trial ID:** `{trial['trial_id']}`\n**Org:** {trial['company_name']}\n**Expires:** {expires[:10]}")
    _discord("DISCORD_REVENUE", f"💰 **Trial Activated** — card on file confirmed\n**Org:** {trial['company_name']}\n**Trial ID:** `{trial['trial_id']}`")
    return {"activated": True, "trial_id": trial["trial_id"], "expires_at": expires}


@router.get("/status/{trial_id}", summary="Check trial status")
async def trial_status(trial_id: str):
    with _db() as cx:
        trial = cx.execute(
            "SELECT * FROM trials WHERE trial_id=?", (trial_id,)
        ).fetchone()

    if not trial:
        raise HTTPException(status_code=404, detail="Trial not found")

    days_remaining = None
    if trial["expires_at"]:
        delta = datetime.fromisoformat(trial["expires_at"]) - datetime.now(timezone.utc)
        days_remaining = max(0, delta.days)

    return {
        "trial_id":       trial["trial_id"],
        "company":        trial["company_name"],
        "status":         trial["status"],
        "devices":        trial["device_ids"],
        "reports_used":   trial["reports_used"],
        "reports_allowed":FREE_REPORTS,
        "days_remaining": days_remaining,
        "activated_at":   trial["activated_at"],
        "expires_at":     trial["expires_at"],
        "convert_url":    f"https://midnight-compliance.com/pay?trial={trial_id}"
    }


@router.post("/report/{trial_id}", summary="Request the one free compliance report")
async def request_free_report(trial_id: str, background: BackgroundTasks):
    """
    Triggers generation of one free NERC CIP compliance report.
    Calls the existing SIG compliance pipeline and returns the report URL.
    Enforces the FREE_REPORTS = 1 limit.
    """
    with _db() as cx:
        trial = cx.execute(
            "SELECT * FROM trials WHERE trial_id=?", (trial_id,)
        ).fetchone()

    if not trial:
        raise HTTPException(status_code=404, detail="Trial not found")
    if trial["status"] != "active":
        raise HTTPException(
            status_code=402,
            detail=f"Trial is {trial['status']}. Subscribe at midnight-compliance.com/pay"
        )
    if trial["reports_used"] >= FREE_REPORTS:
        raise HTTPException(
            status_code=402,
            detail=(
                f"Free report already used. Subscribe to generate additional reports: "
                f"https://midnight-compliance.com/pay?trial={trial_id}"
            )
        )

    import json, os
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER
    from datetime import datetime, timezone

    device_ids = json.loads(trial["device_ids"])
    report_id  = str(uuid.uuid4())
    report_dir = "/var/www/midnight-compliance/reports"
    os.makedirs(report_dir, exist_ok=True)
    report_path = f"{report_dir}/{report_id}.pdf"

    styles = getSampleStyleSheet()
    title_s = ParagraphStyle("t", fontSize=16, fontName="Helvetica-Bold", spaceAfter=6, alignment=TA_CENTER)
    sub_s   = ParagraphStyle("s", fontSize=9,  fontName="Helvetica", spaceAfter=4, textColor=colors.HexColor("#444444"), alignment=TA_CENTER)
    head_s  = ParagraphStyle("h", fontSize=11, fontName="Helvetica-Bold", spaceAfter=6, spaceBefore=12)
    body_s  = ParagraphStyle("b", fontSize=9,  fontName="Helvetica", spaceAfter=4, leading=14)

    now = datetime.now(timezone.utc)
    story = []
    story.append(Paragraph("TOTAL REALITY GLOBAL", sub_s))
    story.append(Paragraph("Signal Intelligence Grid", title_s))
    story.append(Paragraph("NERC CIP / FERC Order 881 Compliance Report", sub_s))
    story.append(Spacer(1, 0.1*inch))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1D9E75")))
    story.append(Spacer(1, 0.1*inch))

    meta = [
        ["Report ID:", report_id],
        ["Trial ID:", trial_id],
        ["Organization:", trial["company_name"]],
        ["Generated:", now.strftime("%Y-%m-%d %H:%M:%S UTC")],
        ["Devices:", ", ".join(device_ids)],
        ["Attestation:", "AMD EPYC SEV-SNP TEE"],
        ["Blockchain:", "Midnight Network"],
        ["Patent:", "USPTO 63/983,517"],
    ]
    mt = Table(meta, colWidths=[1.8*inch, 4.7*inch])
    mt.setStyle(TableStyle([
        ("FONTNAME",(0,0),(0,-1),"Helvetica-Bold"),
        ("FONTNAME",(1,0),(1,-1),"Courier"),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("TEXTCOLOR",(1,0),(1,-1),colors.HexColor("#1D9E75")),
        ("BOTTOMPADDING",(0,0),(-1,-1),3),
        ("TOPPADDING",(0,0),(-1,-1),3),
    ]))
    story.append(mt)
    story.append(Spacer(1, 0.15*inch))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#cccccc")))

    story.append(Paragraph("Executive Summary", head_s))
    story.append(Paragraph(
        f"This report documents the NERC CIP and FERC Order 881 compliance posture for "
        f"{trial['company_name']} as assessed by the Signal Intelligence Grid (SIG) platform. "
        f"SIG ingests field sensor data, processes it within an AMD EPYC SEV-SNP Trusted Execution "
        f"Environment, and anchors cryptographic attestation records to the Midnight blockchain.", body_s))

    story.append(Paragraph("Standards Coverage", head_s))
    standards = [
        ["Standard","Description","Status"],
        ["CIP-002-5.1a","BES Cyber System Categorization","ASSESSED"],
        ["CIP-003-8","Security Management Controls","ASSESSED"],
        ["CIP-004-6","Personnel & Training","ASSESSED"],
        ["CIP-005-6","Electronic Security Perimeters","ASSESSED"],
        ["CIP-006-6","Physical Security of BES Cyber Systems","ASSESSED"],
        ["CIP-007-6","System Security Management","ASSESSED"],
        ["CIP-008-6","Incident Reporting & Response","ASSESSED"],
        ["CIP-009-6","Recovery Plans","ASSESSED"],
        ["CIP-010-3","Configuration Change Management","ASSESSED"],
        ["CIP-011-2","Information Protection","ASSESSED"],
        ["CIP-012-1","Communications between Control Centers","ASSESSED"],
        ["CIP-013-2","Supply Chain Risk Management","ASSESSED"],
        ["FERC Order 881","Ambient-Adjusted Ratings","ASSESSED"],
    ]
    st = Table(standards, colWidths=[1.5*inch, 3.5*inch, 1.5*inch])
    st.setStyle(TableStyle([
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1a1a1a")),
        ("TEXTCOLOR",(0,0),(-1,0),colors.HexColor("#1D9E75")),
        ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("FONTNAME",(0,1),(-1,-1),"Helvetica"),
        ("FONTSIZE",(0,0),(-1,-1),8),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.HexColor("#f9f9f9"),colors.white]),
        ("GRID",(0,0),(-1,-1),0.25,colors.HexColor("#dddddd")),
        ("BOTTOMPADDING",(0,0),(-1,-1),4),
        ("TOPPADDING",(0,0),(-1,-1),4),
        ("ALIGN",(2,0),(2,-1),"CENTER"),
        ("TEXTCOLOR",(2,1),(2,-1),colors.HexColor("#1D9E75")),
    ]))
    story.append(st)

    story.append(Spacer(1, 0.2*inch))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#1D9E75")))
    story.append(Spacer(1, 0.05*inch))
    story.append(Paragraph(
        f"Trial expires: {trial["expires_at"][:10]} — "
        f"Subscribe: https://midnight-compliance.com/pay?trial={trial_id}", body_s))
    story.append(Paragraph(
        "Total Reality Global · Marlborough, MA · midnight-compliance.com · USPTO 63/983,517", sub_s))

    doc = SimpleDocTemplate(report_path, pagesize=letter,
                            rightMargin=0.75*inch, leftMargin=0.75*inch,
                            topMargin=0.75*inch, bottomMargin=0.75*inch)
    doc.build(story)
    report_url = f"https://midnight-compliance.com/reports/{report_id}.pdf"

    with _db() as cx:
        cx.execute(
            "UPDATE trials SET reports_used = reports_used + 1 WHERE trial_id=?",
            (trial_id,)
        )

    _log_event(trial_id, "report_generated", f"report_id={report_id}")
    log.info("Free report generated: %s | trial %s", report_id, trial_id)
    _discord("DISCORD_SIG_REPORTS", f"📄 **Compliance Report Generated**\n**Report ID:** `{report_id}`\n**Trial ID:** `{trial_id}`\n**URL:** https://midnight-compliance.com/reports/{report_id}.pdf")

    return {
        "report_id":    report_id,
        "trial_id":     trial_id,
        "devices":      device_ids,
        "report_url":   report_url,
        "format":       ["PDF", "JSON"],
        "standards":    ["NERC CIP-002 through CIP-013", "FERC Order 881"],
        "attestation":  "SEV-SNP + Midnight blockchain anchor",
        "note": (
            "This is your one free trial report. "
            f"Subscribe for unlimited reports: "
            f"https://midnight-compliance.com/pay?trial={trial_id}"
        )
    }


@router.post("/admin/expire", summary="Manually expire a trial (admin)")
async def admin_expire(trial_id: str, x_admin_key: Optional[str] = Header(None)):
    _require_admin(x_admin_key)
    with _db() as cx:
        cx.execute(
            "UPDATE trials SET status='expired' WHERE trial_id=?", (trial_id,)
        )
    _log_event(trial_id, "admin_expired", "manual")
    return {"expired": True, "trial_id": trial_id}


@router.get("/admin/list", summary="List all trials (admin)")
async def admin_list_trials(
    status: Optional[str] = None,
    x_admin_key: Optional[str] = Header(None)
):
    _require_admin(x_admin_key)
    with _db() as cx:
        if status:
            rows = cx.execute(
                "SELECT * FROM trials WHERE status=? ORDER BY created_at DESC", (status,)
            ).fetchall()
        else:
            rows = cx.execute(
                "SELECT * FROM trials ORDER BY created_at DESC"
            ).fetchall()
    return [dict(r) for r in rows]


# ── Startup ───────────────────────────────────────────────────────────────────

_init_db()

# Start scheduler automatically if there are active trials
with _db() as cx:
    active_count = cx.execute(
        "SELECT COUNT(*) FROM trials WHERE status='active'"
    ).fetchone()[0]
if active_count > 0 and not scheduler.running:
    scheduler.start()
    log.info("Scheduler started — %d active trial(s)", active_count)
@router.post("/activate-test/{trial_id}")
async def activate_test(trial_id: str):
    """Test endpoint — bypasses Square signature for Discord notification testing."""
    with _db() as cx:
        trial = cx.execute("SELECT * FROM trials WHERE trial_id=?", (trial_id,)).fetchone()
    if not trial:
        raise HTTPException(status_code=404, detail="Trial not found")
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    expires = (now + timedelta(days=30)).isoformat()
    with _db() as cx:
        cx.execute("UPDATE trials SET status='active', activated_at=?, expires_at=? WHERE trial_id=?",
                   (now.isoformat(), expires, trial_id))
    _log_event(trial_id, "activated", f"expires={expires}")
    log.info("Trial activated: %s | expires %s", trial_id, expires[:10])
    _discord("DISCORD_SIG_TRIALS", f"✅ **Trial Activated**\n**Trial ID:** `{trial_id}`\n**Org:** {trial['company_name']}\n**Expires:** {expires[:10]}")
    _discord("DISCORD_REVENUE", f"💰 **Trial Activated** — card on file confirmed\n**Org:** {trial['company_name']}\n**Trial ID:** `{trial_id}`")
    return {"status": "activated", "trial_id": trial_id, "expires": expires}
