#!/usr/bin/env bash
#
# One-shot: install Docker + Oracle Free and run the execution grader.
# Run this on a machine where YOU have root/sudo (NOT this sandbox).
#
#   Usage:  bash setup_oracle_grader.sh
#
set -euo pipefail

echo "==> [1/5] Install Docker (Ubuntu/Debian). Assumes sudo works here."
if ! command -v docker >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y docker.io docker-compose-v2
  sudo systemctl enable --now docker 2>/dev/null || true
  # Allow the current user to use docker without sudo for this session.
  sudo usermod -aG docker "$USER" 2>/dev/null || true
  # docker daemon socket may need a fresh group; retry logic below uses sudo anyway.
  echo "    Docker installed."
else
  echo "    Docker already present."
fi

echo "==> [2/5] Start Oracle Free 23ai (first run pulls image + creates DB, 2-5 min)."
docker compose up -d 2>/dev/null || sudo docker compose up -d

echo "==> [3/5] Wait for 'DATABASE IS READY'."
for i in $(seq 1 60); do
  if docker logs oracle-grader 2>&1 | grep -qi 'DATABASE IS READY'; then
    echo "    Database ready after ~${i}x10s."
    break
  fi
  if [ "$i" -eq 60 ]; then echo "    Timed out waiting for readiness. Check: docker logs oracle-grader"; fi
  sleep 10
done

echo "==> [4/5] Install the Python grader deps (thin-mode oracledb, no client libs)."
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate || true
pip install --quiet oracledb sqlglot

echo "==> [5/5] Run the execution grader against the dataset."
ORACLE_DSN="${ORACLE_DSN:-localhost:1521/FREEPDB1}" \
ORACLE_USER="${ORACLE_USER:-system}" \
ORACLE_PASSWORD="${ORACLE_PASSWORD:-oracle}" \
  python grade_db.py oracle_dataset_full.jsonl

echo "==> Done. Report written to grade_db_report.json"
