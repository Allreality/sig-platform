# Signal Intelligence Grid

> Real-time, hardware-attested compliance evidence for transmission line infrastructure.

**Patent:** USPTO 63/983,517 (Pending) — Filed February 15, 2026
**Status:** Operational
**Live API:** `http://87.121.52.49:5010`

---

## Overview

Signal Intelligence Grid (SIG) ingests real-time sensor data from transmission line infrastructure, cryptographically attests every payload using AMD EPYC SEV-SNP, and produces audit-ready compliance records aligned with NERC CIP-007-6 and FERC Order 881.

The platform sits between physical sensor networks (DNP3, Modbus, REST) and regulatory evidence systems, delivering hardware-rooted proof that sensor state at any point in time has not been altered.

---

## How It Works

```
Sensors (TLM / SMARTLINE / DNP3 / Modbus / REST)
        │
        ▼
Protocol Bridges  (protocols/)
        │
        ▼
FastAPI Ingest    (api/sig_ingest.py)
        │
        ▼
SEV-SNP Attestation  (core/sign_payload.py, AMD EPYC)
        │
        ▼
Compliance Record  (NERC CIP-007-6 / FERC Order 881)
```

Every ingested payload is signed within an SEV-SNP-attested execution environment and stored with a SHA-256 tamper-evident hash. Resulting records can be exported as audit-ready compliance packages.

Attestation hashes are anchored to the Midnight blockchain via the SIG Attestation contract:

```
74c4086bd3d6958bea4260202c7dbd1d1f65a3bb530fe27e287b6d7a5ec830e2
```

The contract currently runs on Midnight Preview Network. Mainnet redeployment is on the roadmap.

---

## Architecture

```
sig-platform/
├── core/             # Cryptographic signing and offchain storage
│   ├── sign_payload.py
│   └── store_offchain.py
├── adapters/         # Sensor-vendor adapters
│   ├── lindsey_tlm.py
│   └── lindsey_smartline.py
├── api/              # FastAPI ingest service
│   └── sig_ingest.py
├── protocols/        # Industrial protocol bridges
│   ├── dnp3_bridge.py
│   ├── modbus_bridge.py
│   └── smartline_poller.py
├── tests/
│   └── test_synthetic.py
├── docs/
│   └── DEPLOY.md
└── docker-compose.yml
```

---

## Sensor & Protocol Support

| Sensor / Protocol | Adapter | Status |
|---|---|---|
| Lindsey Systems TLM | `adapters/lindsey_tlm.py` | Implemented |
| Lindsey Systems SMARTLINE | `adapters/lindsey_smartline.py` | Implemented |
| DNP3 | `protocols/dnp3_bridge.py` | Implemented |
| Modbus | `protocols/modbus_bridge.py` | Implemented |
| REST | `api/sig_ingest.py` | Implemented |
| Honeywell, Schneider Electric, Campbell Scientific | — | Roadmap |

---

## Compliance Output

- **NERC CIP-007-6** — System Security Management
- **FERC Order 881** — Ambient-Adjusted Transmission Line Ratings

Each compliance package includes:

- Structured evidence record per sensor event
- AMD EPYC SEV-SNP hardware attestation report
- SHA-256 package hash
- Midnight contract anchor reference
- Audit-ready PDF export

---

## Live Benchmarks

Production deployment, sustained measurement:

- **Attestation latency:** 9–14 ms per record
- **Throughput:** ~70 attestations per second
- **Daily SEV-SNP attestation report:** 06:00 UTC (cron-driven)

---

## Quickstart

Requires Docker, Docker Compose, and Python 3.11+.

```bash
git clone https://github.com/Allreality/sig-platform.git
cd sig-platform
docker-compose up -d
docker-compose logs -f sig-ingest
```

Verify the pipeline end-to-end with the synthetic test:

```bash
python tests/test_synthetic.py
```

FastAPI auto-generated documentation is served at `http://localhost:5010/docs`.

---

## Deployment

Production reference deployment runs on AMD EPYC SEV-SNP hardware (port 5010). See [`docs/DEPLOY.md`](docs/DEPLOY.md) for environment setup, hardware requirements, and operational procedures.

---

## Pilot / Research Collaboration

Utility teams preparing for NERC CIP audits or building FERC Order 881 compliance records can request a no-cost evaluation of the platform against their own transmission-line sensor data.

**Provided:**

- Structured compliance evidence package
- Hardware-attested proof of sensor state
- Audit-ready documentation generated from your dataset

**Required:**

- Sample sensor data (TLM, SMARTLINE, DNP3, or Modbus format)
- 15-minute scoping call

Contact `midnight.trg@gmail.com` for access.

---

## Roadmap

- Lindsey Systems hardware integration (in progress)
- Tier 1 manufacturer adapters: Honeywell, Schneider Electric, Campbell Scientific
- Midnight mainnet redeployment of SIG Attestation contract
- Expanded compliance framework support: NIST SP 800-82, IEC 62443
- Commercial licensing program — pending entity formation

---

## License & Patent

This software and associated documentation are subject to USPTO patent application **63/983,517** (filed February 15, 2026; non-provisional deadline February 15, 2027).

No license is granted at this time. Source is published for review and research collaboration only. Commercial licensing terms will be made available following completion of entity formation.

All rights reserved.

---

## Contact

`midnight.trg@gmail.com`

---

**Total Reality Global** — Marlborough, MA
