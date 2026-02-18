# Signal Intelligence Grid (SIG)
## Patent-Pending Compliance System for Critical Infrastructure

[![Patent](https://img.shields.io/badge/Patent-63%2F983%2C517-blue)](https://patents.google.com/)
[![Status](https://img.shields.io/badge/Status-Live%20Demo-success)](http://87.121.52.49:5010/health)
[![License](https://img.shields.io/badge/License-Proprietary-red)]()

---

## Overview

Signal Intelligence Grid transforms sensor data into legally defensible compliance evidence through hardware-enforced cryptographic attestation and blockchain anchoring.

**Live System:** http://87.121.52.49:5010

**Use Cases:**
- NERC CIP compliance for electric utilities
- FERC Order 881 dynamic line rating verification
- Multi-institutional data collaboration with audit trails
- Critical infrastructure event logging

---

## Patent Protection

- **U.S. Provisional Patent 63/983,517** (Filed: February 15, 2026)
  - "Signal Intelligence Grid for Critical Infrastructure Monitoring"
  
- **Related: U.S. Provisional Patent 63/917,456** (Filed: November 14, 2025)
  - "Hardware-Enforced Compliance Architecture for Secure Multi-Institutional Data Collaboration"

**Core Innovations:**
- Hardware-rooted cryptographic attestation (AMD SEV-SNP)
- Distributed ledger anchoring (Bitcoin/Ethereum/Midnight)
- Automated compliance-grade reporting (NERC CIP/FERC 881)

---

## Architecture
```
┌─────────────────┐
│ Sensor Hardware │ (TLM, SMARTLINE, etc.)
└────────┬────────┘
         │ DNP3/Modbus/REST
         ▼
┌─────────────────┐
│  SIG Ingest API │ (Port 5010)
│   Normalize &   │
│   Attest Data   │
└────────┬────────┘
         │
         ├──► Off-chain Storage (S3/IPFS)
         │
         ├──► Blockchain Anchor (Bitcoin/Midnight)
         │
         └──► Compliance Reports (NERC CIP/FERC 881)
```

---

## Quick Start

### Deploy Locally
```bash
git clone https://github.com/Allreality/sig-platform.git
cd sig-platform
docker-compose up -d
python tests/test_synthetic.py
```

### Test the Live System
```bash
curl http://87.121.52.49:5010/health
```

### Send Test Data
```bash
curl -X POST http://87.121.52.49:5010/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "product": "TLM",
    "data": {
      "current_rms_amps": 485.2,
      "conductor_temp_celsius": 52.3,
      "clearance_to_ground_m": 8.7,
      "load_percentage": 40.4,
      "battery_voltage_v": 3.85,
      "device_serial": "TEST-001",
      "line_segment_id": "LINE-001"
    }
  }'
```

---

## Integration Partners

### Lindsey Systems Integration

Complete adapters for:
- **TLM Conductor Monitor** (DNP3/Modbus/REST)
- **SMARTLINE** (DLR ratings with FERC 881 tagging)
- **SMARTLINE-TCF** (Advanced DLR with forecast curves)

See: [LINDSEY_SIG_INTEGRATION_SPEC.md](LINDSEY_SIG_INTEGRATION_SPEC.md)

---

## Technology Stack

**Backend:**
- FastAPI (Python 3.11)
- PostgreSQL (event ledger)
- Docker Compose

**Attestation:**
- AMD SEV-SNP (hardware root of trust)
- ECDSA signatures (software fallback)
- SHA-256 cryptographic hashing

**Blockchain:**
- Bitcoin (OP_RETURN anchoring)
- Midnight (privacy-preserving compliance)
- Ethereum (optional)

**Storage:**
- S3 (off-chain payloads)
- IPFS (content-addressed storage)
- Local disk (development)

---

## Contact

**Akil Hashim**  
Chief Regent & Systems Analyst  
Total Reality Global  
Marlborough, MA 01752

**Patent:** 63/983,517  
**Live System:** http://87.121.52.49:5010

---

## License

Proprietary. Patent-pending technology.  
Contact for licensing inquiries.
