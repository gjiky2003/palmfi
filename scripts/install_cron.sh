#!/usr/bin/env bash
# Install the PalmFi system cron job.
# Runs the autopilot every hour.
# Also sets up the systemd service if available.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="$PROJECT_DIR/../property-mgmt-ai/.venv/bin/python3"

if [ ! -f "$VENV_PYTHON" ]; then
    VENV_PYTHON=$(command -v python3 || command -v python)
fi

echo "=== PalmFi Cron Installation ==="
echo "Project: $PROJECT_DIR"
echo "Python: $VENV_PYTHON"

# Create cron job (runs every hour)
CRON_LINE="0 * * * * cd $PROJECT_DIR && $VENV_PYTHON -m automation.autopilot --cron >> $PROJECT_DIR/autopilot.log 2>&1"

# Check if already installed
if crontab -l 2>/dev/null | grep -q "automation.autopilot"; then
    echo "[✓] Cron job already installed"
else
    (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
    echo "[✓] Cron job installed (runs every hour)"
fi

# Create systemd service (for continuous daemon mode)
SERVICE_NAME="lumifi-autopilot"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [ -d "/etc/systemd/system" ]; then
    if [ ! -f "$SERVICE_FILE" ]; then
        sudo tee "$SERVICE_FILE" > /dev/null << EOF
[Unit]
Description=PalmFi AI Lending Autopilot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
ExecStart=$VENV_PYTHON -m automation.autopilot --daemon --interval 60
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
        echo "[✓] Systemd service created at $SERVICE_FILE"
        echo "    Run: sudo systemctl enable $SERVICE_NAME && sudo systemctl start $SERVICE_NAME"
    else
        echo "[✓] Systemd service already exists"
    fi
fi

echo ""
echo "=== Next Steps ==="
echo "1. Run the autopilot manually:"
echo "   cd $PROJECT_DIR && $VENV_PYTHON -m automation.autopilot --cron"
echo ""
echo "2. Check autopilot status:"
echo "   cd $PROJECT_DIR && $VENV_PYTHON -m automation.autopilot --status"
echo ""
echo "3. Or run as daemon:"
echo "   sudo systemctl enable lumifi-autopilot"
echo "   sudo systemctl start lumifi-autopilot"
echo ""
echo "Done!"
