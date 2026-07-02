#!/usr/bin/env bash
# deploy_gcp.sh — one command to put AetherCouncil on an always-on GCP VM.
#
# Run this ONCE from Google Cloud Shell (console.cloud.google.com -> Cloud Shell
# icon, top right) from inside the aethercouncil/ directory with your .env
# present. After it finishes, the loop runs 24/7 in the cloud — laptop closed,
# offline, whatever. Cloud Shell is a browser terminal; nothing runs on your
# machine.
#
#   git clone <your repo> && cd <repo>/aethercouncil
#   nano .env          # paste your keys (OPENROUTER, FINNHUB, ALPACA, PAPER_EXECUTE=1)
#   bash deploy/deploy_gcp.sh
#
# Cost: e2-micro in us-central1 is in GCP's Always Free tier (one per account).
# Manage: gcloud compute ssh aethercouncil --zone=us-central1-a
# Stop  : gcloud compute instances stop aethercouncil --zone=us-central1-a
set -euo pipefail

VM_NAME="${VM_NAME:-aethercouncil}"
ZONE="${ZONE:-us-central1-a}"           # us-central1/us-west1/us-east1 = free tier
MACHINE="${MACHINE:-e2-micro}"

HERE="$(cd "$(dirname "$0")/.." && pwd)"   # the aethercouncil/ directory

if [[ ! -f "$HERE/.env" ]]; then
  echo "ERROR: $HERE/.env not found. Create it first (cp .env.example .env; nano .env)"
  exit 1
fi
if ! grep -q "^ALPACA_API_KEY=.\+" "$HERE/.env"; then
  echo "ERROR: ALPACA_API_KEY is empty in .env — the loop can't place paper orders."
  exit 1
fi

echo "== 1/4 creating VM '$VM_NAME' ($MACHINE, $ZONE — Always Free tier) =="
if ! gcloud compute instances describe "$VM_NAME" --zone="$ZONE" >/dev/null 2>&1; then
  gcloud compute instances create "$VM_NAME" \
    --zone="$ZONE" \
    --machine-type="$MACHINE" \
    --image-family=debian-12 --image-project=debian-cloud \
    --boot-disk-size=20GB \
    --no-scopes --no-service-account 2>/dev/null || \
  gcloud compute instances create "$VM_NAME" \
    --zone="$ZONE" \
    --machine-type="$MACHINE" \
    --image-family=debian-12 --image-project=debian-cloud \
    --boot-disk-size=20GB
else
  echo "   (already exists — updating code in place)"
fi

echo "== 2/4 waiting for SSH =="
for i in $(seq 1 12); do
  gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="true" >/dev/null 2>&1 && break
  sleep 10
done

echo "== 3/4 copying code + secrets =="
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="rm -rf ~/aethercouncil && mkdir -p ~/aethercouncil"
# copy the whole directory INCLUDING .env (goes over encrypted SSH, never git)
gcloud compute scp --recurse --zone="$ZONE" "$HERE"/* "$VM_NAME":~/aethercouncil/
gcloud compute scp --zone="$ZONE" "$HERE/.env" "$VM_NAME":~/aethercouncil/.env

echo "== 4/4 installing service on the VM =="
gcloud compute ssh "$VM_NAME" --zone="$ZONE" --command="bash ~/aethercouncil/deploy/setup_vm.sh"

echo ""
echo "======================================================================"
echo " DONE — AetherCouncil is running 24/7 in the cloud."
echo " Close your laptop. It keeps trading, learning, and reporting."
echo ""
echo " Watch live logs : gcloud compute ssh $VM_NAME --zone=$ZONE -- 'sudo journalctl -u aethercouncil -f'"
echo " Green/red board : gcloud compute ssh $VM_NAME --zone=$ZONE -- 'cd /opt/aethercouncil && sudo -u aether python3 run_loop.py --board'"
echo " Track record    : gcloud compute ssh $VM_NAME --zone=$ZONE -- 'cd /opt/aethercouncil && sudo -u aether python3 run_loop.py --track'"
echo " Stop everything : gcloud compute instances stop $VM_NAME --zone=$ZONE"
echo "======================================================================"
