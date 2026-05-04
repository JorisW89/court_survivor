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

echo "Installing Playwright Chromium..."
python -m playwright install chromium --quiet 2>/dev/null || python -m playwright install chromium

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

echo -e "${GREEN}Starting servers...${NC}"
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo "  API docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop."
echo ""

# Kill background jobs on exit
trap 'echo ""; echo "Stopping..."; kill $(jobs -p) 2>/dev/null; exit 0' INT TERM EXIT

ENV=development uvicorn backend.app.main:app --reload --port 8000 &
cd frontend && npm run dev &

wait
