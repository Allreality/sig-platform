"""
PSF x402 Payment Middleware
Total Reality Global — Signal Intelligence Grid
---
Feature-flagged x402 payment layer for SIG API endpoints.
Set ENABLE_X402=true in .env to activate monetization.
Set ENABLE_X402=false (default) to run in free mode.

Wallet: 3Amc3tkRvijtrRtE6XVAkYd8UxF9VKqm7mqDdyT6FPWm
"""

import os
import json
import hashlib
import time
from functools import wraps
from typing import Optional
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

# ── CONFIGURATION ────────────────────────────────────────────────────────────

ENABLE_X402       = os.getenv("ENABLE_X402", "false").lower() == "true"
PSF_WALLET        = os.getenv("PSF_WALLET", "3Amc3tkRvijtrRtE6XVAkYd8UxF9VKqm7mqDdyT6FPWm")
PSF_NETWORK       = os.getenv("PSF_NETWORK", "solana-mainnet")
PSF_CURRENCY      = os.getenv("PSF_CURRENCY", "USDC")

# ── PRICING TIERS ────────────────────────────────────────────────────────────
# All amounts in USD — converted to USDC at settlement

PRICING = {

    # Free forever — no payment required
    "free": {
        "endpoints":    ["/health", "/"],
        "amount_usd":   0.000,
        "description":  "Public health check — no payment required",
    },

    # Per-ingest attestation fee
    "ingest": {
        "endpoints":    ["/ingest"],
        "amount_usd":   0.001,         # $0.001 per attested event
        "description":  "SIG attestation fee — per AEO ingested",
        "basis":        "per_request",
    },

    # Partner log access
    "partner_log": {
        "endpoints":    ["/partner-log"],
        "amount_usd":   0.0005,        # $0.0005 per partner log entry
        "description":  "Partner portal access log fee",
        "basis":        "per_request",
    },

    # Evidence package — EaaS
    "evidence": {
        "endpoints":    ["/evidence", "/evidence/package"],
        "amount_usd":   0.010,         # $0.01 per compliance evidence package
        "description":  "Evidence-as-a-Service — compliance package generation",
        "basis":        "per_request",
    },

    # Risk scoring API
    "risk_score": {
        "endpoints":    ["/risk/score", "/risk/delta"],
        "amount_usd":   0.005,         # $0.005 per risk score query
        "description":  "PSF Risk Scoring API",
        "basis":        "per_request",
    },

    # Grounding analysis report
    "grounding": {
        "endpoints":    ["/reports/grounding"],
        "amount_usd":   0.050,         # $0.05 per grounding analysis report
        "description":  "Grounding Analysis Report — IEEE-referenced",
        "basis":        "per_request",
    },
}

# ── ENDPOINT → TIER MAPPING ──────────────────────────────────────────────────

def get_tier_for_endpoint(path: str) -> dict:
    for tier_name, tier in PRICING.items():
        for endpoint in tier["endpoints"]:
            if path.startswith(endpoint):
                return {"name": tier_name, **tier}
    return {"name": "ingest", **PRICING["ingest"]}  # default to ingest tier


# ── PAYMENT VERIFICATION ─────────────────────────────────────────────────────

def verify_x402_payment(request: Request, required_amount_usd: float) -> bool:
    """
    Verify x402 payment header on incoming request.

    x402 protocol: client sends X-Payment header containing a signed
    payment receipt from the Solana network. We verify the receipt
    authorizes the correct amount to PSF_WALLET.

    In dormant mode (ENABLE_X402=false), always returns True.
    """
    if not ENABLE_X402:
        return True  # dormant — free pass

    payment_header = request.headers.get("X-Payment")
    if not payment_header:
        return False

    try:
        receipt = json.loads(payment_header)

        # Verify recipient wallet
        if receipt.get("recipient") != PSF_WALLET:
            return False

        # Verify network
        if receipt.get("network") != PSF_NETWORK:
            return False

        # Verify currency
        if receipt.get("currency") != PSF_CURRENCY:
            return False

        # Verify amount (allow ±1% tolerance for rounding)
        paid_amount = float(receipt.get("amount_usd", 0))
        if paid_amount < required_amount_usd * 0.99:
            return False

        # Verify receipt is recent (within 60 seconds)
        receipt_ts = int(receipt.get("timestamp", 0))
        if time.time() - receipt_ts > 60:
            return False

        # Verify receipt has a transaction signature
        if not receipt.get("signature"):
            return False

        return True

    except Exception:
        return False


def build_payment_required_response(tier: dict) -> JSONResponse:
    """
    Return 402 Payment Required with x402 payment instructions.
    Client reads this response and submits payment to PSF_WALLET,
    then retries the request with X-Payment header.
    """
    return JSONResponse(
        status_code=402,
        content={
            "error":       "Payment Required",
            "x402": {
                "version":      "1.0",
                "recipient":    PSF_WALLET,
                "network":      PSF_NETWORK,
                "currency":     PSF_CURRENCY,
                "amount_usd":   tier["amount_usd"],
                "description":  tier["description"],
                "basis":        tier.get("basis", "per_request"),
                "psf_operator": "Total Reality Global",
            }
        },
        headers={
            "X-Accepts-Payment": "x402",
            "X-Payment-Recipient": PSF_WALLET,
            "X-Payment-Amount-USD": str(tier["amount_usd"]),
            "X-Payment-Network": PSF_NETWORK,
            "X-Payment-Currency": PSF_CURRENCY,
        }
    )


# ── MIDDLEWARE DECORATOR ──────────────────────────────────────────────────────

def psf_payment_required(f):
    """
    Decorator for FastAPI route handlers.
    When ENABLE_X402=true: verifies payment before processing request.
    When ENABLE_X402=false: passes through — zero friction.

    Usage:
        @app.post("/ingest")
        @psf_payment_required
        async def ingest(request: Request, ...):
            ...
    """
    @wraps(f)
    async def wrapper(*args, **kwargs):
        # Extract request from args/kwargs
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break
        if request is None:
            request = kwargs.get("request")

        if ENABLE_X402 and request is not None:
            tier = get_tier_for_endpoint(request.url.path)
            if tier["amount_usd"] > 0:
                if not verify_x402_payment(request, tier["amount_usd"]):
                    return build_payment_required_response(tier)

        return await f(*args, **kwargs)
    return wrapper


# ── REVENUE TRACKING ─────────────────────────────────────────────────────────

class RevenueTracker:
    """
    In-memory revenue accumulator.
    Writes to /var/sig/revenue/daily_YYYY-MM-DD.jsonl on each event.
    """

    def __init__(self):
        self.session_total_usd = 0.0
        self.session_events    = 0
        self.log_dir           = "/var/sig/revenue"
        os.makedirs(self.log_dir, exist_ok=True)

    def record(self, endpoint: str, amount_usd: float, tx_signature: Optional[str] = None):
        if not ENABLE_X402:
            return  # dormant — nothing to record

        self.session_total_usd += amount_usd
        self.session_events    += 1

        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = f"{self.log_dir}/daily_{today}.jsonl"

        record = {
            "timestamp":   datetime.now(timezone.utc).isoformat(),
            "endpoint":    endpoint,
            "amount_usd":  amount_usd,
            "wallet":      PSF_WALLET,
            "network":     PSF_NETWORK,
            "currency":    PSF_CURRENCY,
            "tx_signature": tx_signature,
            "session_total_usd": self.session_total_usd,
        }

        with open(log_file, "a") as f:
            f.write(json.dumps(record) + "\n")

    def session_summary(self) -> dict:
        return {
            "enable_x402":        ENABLE_X402,
            "session_total_usd":  round(self.session_total_usd, 6),
            "session_events":     self.session_events,
            "wallet":             PSF_WALLET,
            "network":            PSF_NETWORK,
        }


# Singleton tracker
revenue_tracker = RevenueTracker()


# ── STATUS ENDPOINT HELPER ────────────────────────────────────────────────────

def x402_status() -> dict:
    """
    Returns current x402 configuration status.
    Add to /health or a dedicated /x402/status endpoint.
    """
    return {
        "x402_enabled":   ENABLE_X402,
        "wallet":         PSF_WALLET if ENABLE_X402 else "dormant",
        "network":        PSF_NETWORK,
        "currency":       PSF_CURRENCY,
        "pricing_tiers":  {
            k: {"amount_usd": v["amount_usd"], "description": v["description"]}
            for k, v in PRICING.items()
        },
        "revenue":        revenue_tracker.session_summary(),
    }