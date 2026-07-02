#!/usr/bin/env bash
# setup_vm.sh — runs ON the VM (deploy_gcp.sh invokes it). Installs deps,
# installs the systemd service, and starts the loop. Idempotent.
set -euo pipefail

echo "== AetherCouncil VM setup =="

# 1. system deps
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip >/dev/null

# 2. dedicated user + code location
sudo useradd -r -m -s /usr/sbin/nologin aether 2>/dev/null || true
sudo mkdir -p /opt/aethercouncil
sudo cp -r "$HOME/aethercouncil/." /opt/aethercouncil/
sudo chown -R aether:aether /opt/aethercouncil
sudo chmod 600 /opt/aethercouncil/.env

# 3. python deps (system-wide so the service user can import them)
sudo pip3 install -q --break-system-packages -r /opt/aethercouncil/requirements.txt alpaca-py 2>/dev/null \
  || sudo pip3 install -q -r /opt/aethercouncil/requirements.txt alpaca-py

# 4. systemd service: auto-start on boot, auto-restart on crash
sudo cp /opt/aethercouncil/deploy/aethercouncil.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aethercouncil
sudo systemctl restart aethercouncil

sleep 5
echo ""
echo "== status =="
sudo systemctl status aethercouncil --no-pager -l | head -12
echo ""
echo "Done. The loop now runs 24/7, survives reboots, and restarts on crashes."
echo "Logs:   sudo journalctl -u aethercouncil -f"
echo "Board:  cd /opt/aethercouncil && sudo -u aether python3 run_loop.py --board"
echo "Track:  cd /opt/aethercouncil && sudo -u aether python3 run_loop.py --track"
