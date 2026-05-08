#!/usr/bin/env bash
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== Court Survivor — Local Setup ===${NC}"

# Python virtual environment
if [ ! -d ".venv" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate
echo "Installing Python dependencies..."
pip install -r backend/requirements.txt -q

echo "Checking Playwright Chromium..."
if ! python -c "from pathlib import Path; from playwright.sync_api import sync_playwright; p = sync_playwright().start(); browser = p.chromium; exists = Path(browser.executable_path).exists(); p.stop(); raise SystemExit(0 if exists else 1)" 2>/dev/null; then
    echo "Installing Playwright Chromium..."
    python -m playwright install chromium
fi

echo "Running database migrations..."
(cd backend && alembic upgrade head)

# Frontend
if [ ! -d "frontend/node_modules" ]; then
    echo "Installing frontend dependencies..."
    cd frontend && npm install --silent && cd ..
fi

# .env
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${YELLOW}Created .env from .env.example — edit it to set a real SECRET_KEY.${NC}"
fi

# Free ports if already in use
for port in 8000 3000; do
    pids=$(lsof -ti tcp:$port 2>/dev/null) || true
    if [ -n "$pids" ]; then
        echo "Freeing port $port (PIDs: $pids)..."
        echo $pids | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
done

echo -e "${GREEN}Starting servers...${NC}"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo "  API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop."
echo ""

# Kill background jobs on exit
trap 'echo ""; echo "Stopping..."; kill $(jobs -p) 2>/dev/null; exit 0' INT TERM EXIT

(cd backend && ENV=development uvicorn app.main:app --reload --port 8000) &
cd frontend && npm run dev &

wait
