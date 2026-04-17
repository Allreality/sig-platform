"""
x402_middleware.py — stub
Real x402 payment enforcement goes here when payment layer is wired.
Currently passes all requests through for trial and development use.
"""
import logging
from functools import wraps

log = logging.getLogger("sig.x402")

def psf_payment_required(func):
    """
    Decorator stub — payment enforcement placeholder.
    Replace with real x402 payment check when live.
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        return await func(*args, **kwargs)
    return wrapper

def x402_status() -> dict:
    return {"status": "stub", "mode": "passthrough", "live": False}

class RevenueTracker:
    def record(self, endpoint: str, amount: float):
        log.info("Revenue event: %s — $%.4f (stub)", endpoint, amount)

revenue_tracker = RevenueTracker()
