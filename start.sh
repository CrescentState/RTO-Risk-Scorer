#!/bin/bash
# Render startup script
# Generates synthetic data if missing, then serves the API with uvicorn.

set -e

echo "[STARTUP] Generating synthetic data if needed..."
if [ ! -f "synthetic_data/customers.csv" ] || [ ! -f "synthetic_data/orders.csv" ]; then
    echo "[STARTUP] Synthetic data not found, generating..."
    python -m synthetic_data.generator
else
    echo "[STARTUP] Synthetic data exists, skipping generation"
fi

PORT="${PORT:-8000}"
echo "[STARTUP] Starting application on port ${PORT}..."
exec python -m uvicorn main:app --host 0.0.0.0 --port "${PORT}"
