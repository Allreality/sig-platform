# SIG Agent System — Deployment Guide
# Total Reality Global | Feb 22, 2026

## Structure

```
sig-agents/
├── orchestrator.py          # Main entry point — runs all 7 bots
├── requirements.txt
├── shared/
│   ├── activity_log.py      # Shared append-only log (all bots write here)
│   └── aeo_schema.py        # AEO constants and validation (read-only)
└── bots/
    ├── partner_followup.py  # Bot 1 — Partner/outreach tracking
    ├── evidence_packaging.py # Bot 2 — EaaS automation
    ├── health_monitor.py    # Bot 3 — VPSBG system health
    ├── grounding_research.py # Bot 4 — Grounding analysis + billing
    ├── sbir_prep.py         # Bot 5 — SBIR readiness tracking
    ├── legal_coordination.py # Bot 6 — Olayimika/IP/LLC tracking
    └── r2_telemetry.py      # Bot 7 — Cloudflare R2 offload (staging mode)
```

## Deploy to VPSBG

```bash
# Copy to server
scp -r sig-agents/ root@87.121.52.49:/home/sig-agents-system/

# SSH in
ssh root@87.121.52.49
cd /home/sig-agents-system

# Install dependencies (into existing SIG venv or new one)
pip install -r requirements.txt --break-system-packages

# Create required directories
mkdir -p /var/sig/agents/state
mkdir -p /var/sig/evidence
mkdir -p /var/sig/grounding-reports
mkdir -p /var/sig/sbir
mkdir -p /var/sig/legal
mkdir -p /var/sig/r2-staging
mkdir -p /var/sig/r2-archive

# Copy .env from sig-platform
cp /home/sig-platform/.env .env

# Test single bot
python orchestrator.py --bot health_monitor

# Run all bots
python orchestrator.py

# Check activity log
python orchestrator.py --status

# Check pending x402 fees
python orchestrator.py --fees
```

## Cron Schedule (add to crontab)

```cron
# Health monitor — every 30 min
*/30 * * * * cd /home/sig-agents-system && python orchestrator.py --bot health_monitor >> /var/log/sig-agents.log 2>&1

# Partner follow-up — daily 09:00 UTC
0 9 * * * cd /home/sig-agents-system && python orchestrator.py --bot partner_followup >> /var/log/sig-agents.log 2>&1

# Evidence packaging — every 6 hours
0 */6 * * * cd /home/sig-agents-system && python orchestrator.py --bot evidence_packaging >> /var/log/sig-agents.log 2>&1

# Grounding research — every 6 hours
0 */6 * * * cd /home/sig-agents-system && python orchestrator.py --bot grounding_research >> /var/log/sig-agents.log 2>&1

# SBIR prep — daily 08:00 UTC
0 8 * * * cd /home/sig-agents-system && python orchestrator.py --bot sbir_prep >> /var/log/sig-agents.log 2>&1

# Legal coordination — daily 08:00 UTC
0 8 * * * cd /home/sig-agents-system && python orchestrator.py --bot legal_coordination >> /var/log/sig-agents.log 2>&1

# R2 telemetry — every 4 hours
0 */4 * * * cd /home/sig-agents-system && python orchestrator.py --bot r2_telemetry >> /var/log/sig-agents.log 2>&1
```

## Activating x402

When ready to flip x402 live:
1. Confirm first partner test session complete
2. In /home/sig-platform/.env: set ENABLE_X402=true
3. All pending fees in /var/sig/agents/x402_pending.jsonl will begin settling

## Activating R2

When Cloudflare R2 is configured:
1. Add to .env:
   R2_ENABLED=true
   R2_ACCOUNT_ID=your_account_id
   R2_BUCKET_NAME=sig-telemetry
   R2_ACCESS_KEY_ID=your_key
   R2_SECRET_ACCESS_KEY=your_secret
   R2_ENDPOINT_URL=https://your_account_id.r2.cloudflarestorage.com
2. R2 bot will automatically switch from staging to upload mode

## Marking Events (manual triggers)

```python
# Partner replied
from bots.partner_followup import mark_replied
mark_replied("lindsey_systems", notes="Dr. Lindsey responded, interested in demo")

# Follow-up sent
from bots.partner_followup import mark_followup_sent
mark_followup_sent("cecil_elie", day=5)

# Update SBIR checklist
from bots.sbir_prep import update_item
update_item("registration", "uei_cage", "COMPLETE", value="UEI: ABC123 CAGE: XY456")

# Update legal timeline
from bots.legal_coordination import update_timeline_item
update_timeline_item("call_olayimika", "COMPLETE", notes="Call held Feb 25 2026")

# Mark question answered
from bots.legal_coordination import update_question
update_question("q6", "ANSWERED", answer="LLC recommended before any agreements")
```

## Invariants — DO NOT VIOLATE

- No bot modifies /home/sig-platform/ (SIG core)
- No bot modifies AEO schema or routing logic
- x402 fees are recorded but never settled until ENABLE_X402=true
- All log writes are APPEND-ONLY
- All file operations are idempotent — safe to re-run
