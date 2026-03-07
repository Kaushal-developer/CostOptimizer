#!/bin/bash
set -e

echo "=== CostOptimizer Setup ==="

# Check Python
command -v python3 >/dev/null 2>&1 || { echo "Python 3.11+ required"; exit 1; }

# Copy env file
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created .env — edit it to add cloud credentials and API keys"
fi

# Install core deps (SQLite, no Docker needed)
echo "Installing core dependencies..."
pip install -e ".[dev]"

# Optional: install cloud SDKs
echo ""
echo "Core installed. To add cloud providers, run:"
echo "  pip install -e '.[aws]'       # AWS support"
echo "  pip install -e '.[azure]'     # Azure support"
echo "  pip install -e '.[gcp]'       # GCP support"
echo "  pip install -e '.[llm]'       # Claude AI explanations"
echo "  pip install -e '.[all]'       # Everything"
echo ""

# Create SQLite DB with tables
echo "Initializing database (SQLite)..."
python3 -c "
import asyncio
from src.core.database import engine, Base
from src.models import *
async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print('Database tables created.')
asyncio.run(init())
"

# Frontend (optional)
if command -v node >/dev/null 2>&1; then
    echo "Installing frontend dependencies..."
    cd frontend && npm install && cd ..
else
    echo "Node.js not found — skipping frontend setup (optional)"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Start the API:       uvicorn src.api.main:app --reload"
echo "Start the frontend:  cd frontend && npm run dev"
echo ""
echo "No Docker, Redis, or Postgres needed for local dev!"
echo "SQLite database at ./costoptimizer.db"
