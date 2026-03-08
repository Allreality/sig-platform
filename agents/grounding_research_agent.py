"""
SIG Grounding Research Agent
============================
Reads live attested telemetry from the SIG off-chain store,
analyzes electrical and thermal patterns, and generates IEEE-referenced
grounding design recommendations using Claude AI.

Schedule: Daily via cron at 06:00 UTC
Output:   /var/sig/reports/grounding_YYYY-MM-DD.json
"""

import os, json, glob, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
import anthropic

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [SIG-GROUNDING] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/var/sig/logs/grounding_agent.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
OFFCHAIN_DIR   = "/var/sig/offchain/sig"
REPORT_DIR     = "/var/sig/reports"
LOOKBACK_HOURS = 24
MAX_RECORDS    = 200
MODEL          = "claude-opus-4-6"

# ── IEEE Standard References ──────────────────────────────────────────────────
IEEE_STANDARDS = {
    "IEEE_80":  "IEEE Guide for Safety in AC Substation Grounding — touch/step voltage, ground grid design",
    "IEEE_81":  "IEEE Guide for Measuring Earth Resistivity, Ground Impedance, and Earth Surface Potentials",
    "IEEE_837": "IEEE Standard for Qualifying Permanent Connections Used in Substation Grounding",
    "IEEE_142": "IEEE Recommended Practice for Grounding of Industrial and Commercial Power Systems (Green Book)",
    "NERC_FAC_001": "NERC FAC-001 — Facility Connection Requirements, grounding as part of interconnection standards",
    "NERC_CIP_007": "NERC CIP-007-6 — Systems Security Management, physical grounding for equipment protection",
    "IEC_60364": "IEC 60364 — Electrical Installations, grounding and bonding requirements",
}

SYSTEM_PROMPT = """You are a senior power systems engineer specializing in transmission line grounding design
and critical infrastructure protection. You analyze real-time telemetry data from Lindsey Systems TLM and
SMARTLINE sensors deployed on transmission lines.

Your role is to:
1. Identify grounding risks from live electrical and thermal data
2. Generate specific, actionable grounding design recommendations
3. Reference exact IEEE standards and clauses in every recommendation
4. Prioritize recommendations by criticality (CRITICAL, HIGH, MEDIUM, LOW)
5. Estimate fault current exposure and ground potential rise (GPR) risks

IEEE Standards you must reference where applicable:
- IEEE 80: Touch/step voltage, ground grid design
- IEEE 81: Earth resistivity and ground impedance measurement
- IEEE 837: Qualifying permanent grounding connections
- IEEE 142: Grounding of industrial and commercial power systems
- NERC FAC-001: Facility connection requirements
- NERC CIP-007-6: Systems security management
- IEC 60364: Electrical installations grounding

Format your analysis as structured JSON with this exact schema:
{
  "analysis_summary": "brief overview of findings",
  "risk_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "fault_current_exposure": {
    "estimated_max_fault_amps": 0,
    "gpr_risk": "description",
    "ieee_80_compliance": "compliant|review_required|non_compliant"
  },
  "recommendations": [
    {
      "priority": "CRITICAL|HIGH|MEDIUM|LOW",
      "issue": "specific problem identified",
      "recommendation": "specific action to take",
      "ieee_reference": "IEEE XX Section Y.Z",
      "rationale": "why this matters for equipment protection",
      "estimated_impact": "what this prevents or improves"
    }
  ],
  "grounding_design_notes": {
    "conductor_sizing": "recommendation with IEEE 80 reference",
    "ground_rod_depth": "recommendation based on soil/thermal data",
    "bonding_requirements": "IEEE 837 bonding recommendations",
    "inspection_interval": "recommended inspection frequency"
  },
  "data_quality_notes": "observations about data gaps or anomalies"
}

Be precise. Reference specific clause numbers when known. Never give generic advice.
Every recommendation must be traceable to the telemetry data provided.
Return only valid JSON — no markdown, no explanation outside the JSON."""


def load_recent_records() -> list:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    records = []
    pattern = os.path.join(OFFCHAIN_DIR, "*.json")
    files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    for fpath in files[:MAX_RECORDS * 2]:
        try:
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
            if mtime < cutoff:
                continue
            with open(fpath, "r") as f:
                rec = json.load(f)
            records.append(rec)
            if len(records) >= MAX_RECORDS:
                break
        except Exception as e:
            log.warning(f"Skipping {fpath}: {e}")
    log.info(f"Loaded {len(records)} records from last {LOOKBACK_HOURS}h")
    return records


def extract_telemetry_summary(records: list) -> dict:
    if not records:
        return {"total_records": 0, "note": "No telemetry available — baseline analysis only"}

    tlm_records       = [r for r in records if r.get("source_product") == "TLM"]
    smartline_records = [r for r in records if r.get("source_product") == "SMARTLINE"]

    summary = {
        "total_records":         len(records),
        "tlm_count":             len(tlm_records),
        "smartline_count":       len(smartline_records),
        "analysis_window_hours": LOOKBACK_HOURS,
        "assets":                list({r.get("asset_id", "UNKNOWN") for r in records}),
        "tlm_metrics":           {},
        "smartline_metrics":     {},
        "raw_samples":           records[:10],
    }

    if tlm_records:
        currents   = [r["electrical"]["current_rms_amps"]       for r in tlm_records if "electrical" in r]
        temps      = [r["mechanical"]["conductor_temp_celsius"]  for r in tlm_records if "mechanical" in r]
        clearances = [r["mechanical"]["clearance_to_ground_m"]  for r in tlm_records if "mechanical" in r]
        loads      = [r["electrical"]["load_percentage"]        for r in tlm_records if "electrical" in r]
        if currents:
            summary["tlm_metrics"] = {
                "current_rms_amps":       {"min": min(currents),   "max": max(currents),   "avg": round(sum(currents)/len(currents), 2)},
                "conductor_temp_celsius": {"min": min(temps),      "max": max(temps),      "avg": round(sum(temps)/len(temps), 2)}      if temps      else {},
                "clearance_to_ground_m":  {"min": min(clearances), "max": max(clearances), "avg": round(sum(clearances)/len(clearances), 2)} if clearances else {},
                "load_percentage":        {"min": min(loads),      "max": max(loads),      "avg": round(sum(loads)/len(loads), 2)}      if loads      else {},
                "sag_alerts":             sum(1 for r in tlm_records if r.get("mechanical", {}).get("sag_alert")),
                "high_load_events":       sum(1 for r in tlm_records if r.get("electrical", {}).get("load_percentage", 0) > 90),
            }

    if smartline_records:
        dlr_vals = [r["ratings"]["dlr_current_amps"] for r in smartline_records if "ratings" in r]
        aar_vals = [r["ratings"]["aar_amps"]         for r in smartline_records if "ratings" in r]
        ratios   = [r["ratings"]["dlr_vs_aar_ratio"] for r in smartline_records if "ratings" in r and r["ratings"].get("dlr_vs_aar_ratio")]
        if dlr_vals:
            summary["smartline_metrics"] = {
                "dlr_current_amps":    {"min": min(dlr_vals), "max": max(dlr_vals), "avg": round(sum(dlr_vals)/len(dlr_vals), 2)},
                "aar_amps":            {"min": min(aar_vals), "max": max(aar_vals), "avg": round(sum(aar_vals)/len(aar_vals), 2)} if aar_vals else {},
                "dlr_vs_aar_ratio":    {"min": round(min(ratios), 4), "max": round(max(ratios), 4), "avg": round(sum(ratios)/len(ratios), 4)} if ratios else {},
                "dlr_below_aar_events": sum(1 for r in smartline_records if "RATING_DECLINING" in r.get("compliance", {}).get("alerts", [])),
            }

    return summary


def run_grounding_analysis(summary: dict) -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment")

    client = anthropic.Anthropic(api_key=api_key)

    user_message = f"""Analyze the following live telemetry summary from the Signal Intelligence Grid
and generate grounding design recommendations to protect transmission line equipment.

TELEMETRY SUMMARY (last {LOOKBACK_HOURS} hours):
{json.dumps(summary, indent=2, default=str)}

Generate a comprehensive grounding analysis with specific IEEE-referenced recommendations.
Return only valid JSON matching the schema in your instructions."""

    log.info("Sending telemetry to Claude for grounding analysis...")
    message = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}]
    )

    raw_response = message.content[0].text
    log.info(f"Received analysis — {len(raw_response)} chars, tokens: {message.usage.input_tokens} in / {message.usage.output_tokens} out")

    try:
        clean = raw_response.strip()
        if clean.startswith("```"):
            clean = clean.split("```")[1]
            if clean.startswith("json"):
                clean = clean[4:]
        analysis = json.loads(clean.strip())
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse JSON response: {e}")
        analysis = {"raw_response": raw_response, "parse_error": str(e)}

    return analysis


def save_report(summary: dict, analysis: dict) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    os.makedirs("/var/sig/logs", exist_ok=True)

    date_str    = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report_path = os.path.join(REPORT_DIR, f"grounding_{date_str}.json")

    report = {
        "report_type":               "grounding_design_analysis",
        "generated_at":              datetime.now(timezone.utc).isoformat(),
        "generated_by":              "SIG-Grounding-Research-Agent-v1.0",
        "ai_model":                  MODEL,
        "platform":                  "Signal Intelligence Grid — Total Reality Global",
        "patent_pending":            "USPTO 63/983,517",
        "ieee_standards_referenced": list(IEEE_STANDARDS.keys()),
        "telemetry_summary":         summary,
        "grounding_analysis":        analysis,
    }

    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    log.info(f"Report saved: {report_path}")
    return report_path


def main():
    log.info("=" * 60)
    log.info("SIG Grounding Research Agent — Starting")
    log.info(f"Analysis window: last {LOOKBACK_HOURS} hours")
    log.info("=" * 60)

    try:
        from dotenv import load_dotenv
        load_dotenv("/home/sig-platform/.env")
        log.info("Loaded .env")
    except ImportError:
        pass

    records  = load_recent_records()
    summary  = extract_telemetry_summary(records)
    analysis = run_grounding_analysis(summary)

    risk = analysis.get("risk_level", "UNKNOWN")
    log.info(f"Risk level: {risk}")

    recs     = analysis.get("recommendations", [])
    critical = [r for r in recs if r.get("priority") == "CRITICAL"]
    if critical:
        log.warning(f"{len(critical)} CRITICAL recommendation(s) generated")

    report_path = save_report(summary, analysis)

    log.info("=" * 60)
    log.info(f"Complete — {len(recs)} recommendations | Report: {report_path}")
    log.info("=" * 60)
    return report_path


if __name__ == "__main__":
    main()