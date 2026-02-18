# LINDSEY SYSTEMS × SIG INTEGRATION SPECIFICATION
## Signal Intelligence Grid - Transmission Line Sensor Integration
### Patent Application 63/983,517 | Total Reality Global

---

## OVERVIEW

This document specifies the complete technical integration of Lindsey Systems' 
transmission-line sensor products into the Signal Intelligence Grid (SIG) 
architecture. Every measurement ingested from Lindsey hardware flows through 
the SIG canonical schema, receives SHA-256 attestation, is stored off-chain, 
and is anchored on-chain — producing audit-grade evidence for NERC CIP-007 
and FERC Order 881 compliance.

---

## 1. SIG CANONICAL SCHEMA

All Lindsey sensor data normalizes to this universal structure before hashing 
and anchoring. This is the foundation of every integration adapter.
```json
{
  "sig_event": {
    "schema_version": "1.0",
    "event_id": "uuid-v4",
    "node_id": "LINDSEY-TLM-001-ASSET-XYZ",
    "asset_id": "SUBSTATION-ALPHA-LINE-3",
    "weather_cell_id": "WCELL-MA-042",
    "cip_classification": "BES-002",
    "ferc_881_tag": true,
    "source_vendor": "lindsey_systems",
    "source_product": "TLM|SMARTLINE|SMARTLINE_TCF",
    "timestamp_utc": "2026-02-17T14:22:30.000000Z",
    "payload_hash": "sha256:a1b2c3d4...",
    "payload_uri": "ipfs://Qm.../or/s3://bucket/key",
    "data": {},
    "attestation": {
      "node_signature": "ecdsa:...",
      "payload_hash": "sha256:...",
      "signed_at": "2026-02-17T14:22:30Z"
    },
    "ledger": {
      "tx_id": "...",
      "blockchain": "bitcoin|ethereum|midnight"
    },
    "compliance": {
      "nerc_cip_standard": "CIP-007-6",
      "nerc_cip_requirement": "R4",
      "ferc_order": "881",
      "audit_ready": true
    }
  }
}
```

See full specification at: https://github.com/Allreality/sig-platform

---

## DEPLOYED SYSTEM

**Live API:** http://87.121.52.49:5010

**Test endpoint:** http://87.121.52.49:5010/health

**Repository:** https://github.com/Allreality/sig-platform

**Patent:** U.S. Provisional 63/983,517 (Filed Feb 15, 2026)

**Related Patent:** U.S. Provisional 63/917,456 (Filed Nov 14, 2025)

