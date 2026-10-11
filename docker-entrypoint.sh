#!/bin/sh
# API only — worker runs as a separate compose service (realsmaker-worker).
set -eu
cd /app
exec uvicorn api.main:app --host 0.0.0.0 --port 8770 --workers 1
