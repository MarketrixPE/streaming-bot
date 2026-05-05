#!/usr/bin/env bash
# Auto-release de numeros vencidos + purga de SMS antiguos.
# Crontab: */5 * * * * /opt/streaming-bot/infra/sms_hub/scripts/housekeeping.sh
set -euo pipefail
source /opt/streaming-bot/infra/sms_hub/.env

psql "$DATABASE_URL" <<'SQL'
UPDATE farm_numbers
SET released_at = NOW()
WHERE released_at IS NULL
  AND expires_at < NOW();

DELETE FROM farm_sms_inbox
WHERE consumed_at IS NOT NULL
  AND consumed_at < NOW() - INTERVAL '7 days';

DELETE FROM farm_numbers
WHERE released_at IS NOT NULL
  AND released_at < NOW() - INTERVAL '30 days';
SQL
