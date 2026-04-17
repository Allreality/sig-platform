#!/bin/bash
# ─────────────────────────────────────────────────────────
# SIG Server Monitor — Deploy Script
# Run this on VPSBG (87.121.52.49) as root
# ─────────────────────────────────────────────────────────

set -e

MONITOR_DIR="/root/server-monitor"
SCRIPT_NAME="sig_server_monitor.py"

echo ">>> Creating monitor directory..."
mkdir -p $MONITOR_DIR

echo ">>> Installing dependencies..."
pip3 install anthropic requests --break-system-packages

echo ">>> Copying monitor script..."
cp $SCRIPT_NAME $MONITOR_DIR/
chmod +x $MONITOR_DIR/$SCRIPT_NAME

echo ""
echo "─────────────────────────────────────────────────────"
echo "STEP 1 — Set your environment variables in /etc/environment or ~/.bashrc:"
echo ""
echo "  export ANTHROPIC_API_KEY='your-key-here'"
echo ""
echo "STEP 2 — Set your Discord webhook in the script:"
echo "  nano $MONITOR_DIR/$SCRIPT_NAME"
echo "  → Find DISCORD_WEBHOOK_URL and paste your webhook"
echo ""
echo "STEP 3 — Test it manually first:"
echo "  python3 $MONITOR_DIR/$SCRIPT_NAME"
echo ""
echo "STEP 4 — Install cron job (every 15 minutes):"
echo "  crontab -e"
echo ""
echo "  Paste this line:"
echo "  */15 * * * * ANTHROPIC_API_KEY=\$ANTHROPIC_API_KEY python3 /root/server-monitor/sig_server_monitor.py >> /root/server-monitor/cron.log 2>&1"
echo ""
echo "STEP 5 — Get your Discord webhook URL:"
echo "  Discord Server → Channel Settings → Integrations → Webhooks → New Webhook → Copy URL"
echo "─────────────────────────────────────────────────────"
echo ""
echo ">>> Deploy complete."
