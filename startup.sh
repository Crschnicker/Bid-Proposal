#!/bin/bash
set -e

# Start Gunicorn
exec gunicorn --bind 0.0.0.0:${PORT:-5000} \
    --workers 4 \
    --threads 2 \
    --timeout 120 \
    --access-logfile '-' \
    --error-logfile '-' \
    app:app