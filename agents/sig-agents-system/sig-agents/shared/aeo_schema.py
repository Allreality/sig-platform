"""
shared/aeo_schema.py
====================
AEO schema constants and validation helpers.
Agents reference this — never modify SIG core logic.
Read-only reference layer.
"""

# Compliance standards supported
SUPPORTED_STANDARDS = ["NERC-CIP-007-6", "FERC-881", "NIST-800-171"]

# Stakeholder classes
STAKEHOLDER_CLASSES = ["OPERATOR", "INSURER", "REGULATOR", "COMMUNITY"]

# Economic event types
ECONOMIC_EVENT_TYPES = [
    "PERFORMANCE_CREDIT",
    "UNDERWRITING_ADJUSTMENT",
    "COMPLIANCE_CREDIT",
    "COMPLIANCE_PENALTY",
    "COMMUNITY_COMPENSATION",
    "PSF_ROUTING_FEE",
]

# x402 pricing tiers (USD)
X402_PRICING = {
    "/health":       0.000,
    "/ingest":       0.001,
    "/partner-log":  0.0005,
    "/evidence":     0.010,
    "/risk/score":   0.005,
    "/grounding":    0.050,
}

# AEO required fields
AEO_REQUIRED_FIELDS = [
    "event_id",
    "payload_hash",
    "payload_uri",
    "attestation",
    "compliance",
    "data",
    "created_at",
]

# SIG ingest API base URL
SIG_API_BASE = "http://localhost:5010"

# Neon Postgres table
SIG_EVENTS_TABLE = "sig_events"

# Evidence storage
EVIDENCE_DIR = "/var/sig/evidence"
OFFCHAIN_DIR = "/var/sig/offchain/sig"
PARTNER_LOG_DIR = "/var/sig/partner-logs"
AGENT_STATE_DIR = "/var/sig/agents/state"


def validate_aeo(aeo: dict) -> tuple[bool, list]:
    """
    Validate an AEO dict against required fields.
    Returns (is_valid, missing_fields)
    Does NOT modify the AEO.
    """
    missing = [f for f in AEO_REQUIRED_FIELDS if f not in aeo]
    return len(missing) == 0, missing
