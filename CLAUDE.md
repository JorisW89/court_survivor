# Court Survivor — Claude Collaboration Guide

## What this app does
Squash survivor game: users pick one player per tournament round. Correct pick → you survive and earn points. Wrong pick → streak resets. Can't repick the same player in the same tournament.

## Stack
| Layer | Tech |
|---|---|
| Backend | FastAPI + SQLAlchemy 2 + Alembic (SQLite dev / PostgreSQL prod) |
| Frontend | React 18 + Vite + Tailwind CSS + Axios |
| Auth | JWT (python-jose, HS256, 7-day expiry) + bcrypt |
| Scraper | Playwright (Chromium) + BeautifulSoup → PSA squash tour website |
| Deploy | Render.com: separate Web Service (FastAPI) + Static Site (React), configured manually in dashboard |

## Running locally
```bash
./local_run.sh   # one-shot: creates venv, installs deps, runs migrations, starts both servers
```
- Backend: http://localhost:8000
- Frontend: http://localhost:3000
- Vite proxies `/api/*` → backend

## Key file map
```
backend/app/
  main.py            # FastAPI app, lifespan, router registration
  models.py          # All 12 SQLAlchemy models
  schemas.py         # All Pydantic request/response schemas
  config.py          # Pydantic settings (reads .env)
  auth.py            # JWT encode/decode, password hash
  player_utils.py    # normalize_player_name()
  time_utils.py      # has_time_passed()
  seed.py            # Dev seed data
  routers/
    auth.py          # /api/auth  — register, login, me
    games.py         # /api/games — CRUD, leaderboard, draw
    picks.py         # /api/picks — submit, delete
    groups.py        # /api/groups — create, join, leaderboard
    tournaments.py   # /api/tournaments
    admin.py         # /api/admin/scrape (X-Admin-Secret header)
  services/
    game_engine.py   # Scoring, streak calc, round evaluation
    scraper_service.py # PSA sync → DB

frontend/src/
  App.jsx            # Router
  api/client.js      # Axios instance (auto-injects JWT, handles 401)
  context/AuthContext.jsx  # Auth state + token in localStorage
  pages/             # Home, GameDetail, GameLeaderboard, Login, Register, Groups, GroupDetail
  components/        # Layout, Navbar, GameCard, SquashIcon

main.py              # Root-level PSA Playwright scraper (called by scraper_service.py)
```

## Data model — key invariants

**Game creation:** One `Game` per `(tournament_id, division)`. Created automatically by scraper sync.

**Enrollment:** `GameParticipant` is auto-created on first `Pick` — users don't manually join.

**Pick uniqueness:** DB constraint `uq_pick` on `(game_id, user_id, round_id)` — one pick per user per round.

**Scoring:**
- Points per correct pick = `streak_length + ranking_bonus`
- Streak = consecutive correct picks (resets on wrong pick OR missing deadline)
- Ranking bonus: picked player rank vs opponent rank (gap ≥1 → +1, ≥5 → +2, ≥10 → +3)
- Rankings compared against `TournamentRankingSnapshot` (captured at tournament start, not live)
- Missing a deadline = streak resets, zero points for that round

**Round statuses:** `upcoming` → `open` → `locked` → `completed`
- Picks only accepted when round is `open`
- `pick_deadline` = 1 hour before the first match in round (`compute_pick_deadline` in `scraper_service.py`)

**Datetime handling:** All datetimes stored in UTC with timezone info. Use `_utcnow()` from `models.py`, not `datetime.utcnow()` (deprecated). Never strip timezone info.

**Player deduplication:** Always use `normalize_player_name()` from `player_utils.py` before DB lookups. The `normalized_name` column is the unique key for players.

## Database migrations
```bash
# After changing models.py:
cd backend
alembic revision --autogenerate -m "description"
alembic upgrade head
```
Never edit migration files retroactively if already applied in prod.

## Deployment (Render.com)
Two manually configured services in the Render dashboard — no blueprint file drives this.

**Web Service (FastAPI backend):**
- Root directory: `backend`
- Build: `pip install -r requirements.txt && PLAYWRIGHT_BROWSERS_PATH=/opt/render/project/pw-browsers python -m playwright install chromium --only-shell`
- Start: `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Environment variables set in dashboard (see list below)

**Static Site (React frontend):**
- Root directory: `frontend`
- Build: `npm ci && npm run build`
- Publish directory: `dist`
- Rewrite rule: `/* → /index.html` (SPA)
- `VITE_API_BASE_URL` set in dashboard

> Note: `render.yaml` exists in the repo but is **not used** — config lives in the Render dashboard.

## Environment variables
```
DATABASE_URL          sqlite:///./court_survivor.db  (prod: postgresql://...)
SECRET_KEY            jwt signing secret
ACCESS_TOKEN_EXPIRE_MINUTES  10080 (7 days)
ENV                   development | production  (affects scraper scheduling)
CORS_ORIGINS          comma-separated allowed origins
ADMIN_SECRET          header secret for /api/admin/scrape
VITE_API_BASE_URL     /api  (set in Render static site env)
PLAYWRIGHT_BROWSERS_PATH   (prod only: /opt/render/project/pw-browsers)
```

## Common patterns

**Protected endpoint:**
```python
@router.get("/something")
def get_something(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
```

**Optional auth endpoint:**
```python
def get_something(db: Session = Depends(get_db), current_user: Optional[User] = Depends(get_optional_user)):
```

**Frontend API call:**
```js
import api from '../api/client'
const { data } = await api.get('/games')  // token auto-injected
```

**Adding a new router:**
Register it in `backend/app/main.py` with `app.include_router(...)`.

## Scraper architecture
`scraper_service.py` calls `main.py --json` as a subprocess → parses JSON output → upserts tournaments, rounds, matches, players, rankings, and snapshot rankings into DB → triggers `evaluate_all_completed_rounds()` in `game_engine.py`.

The scraper runs:
- **Dev:** once on startup (via lifespan in `backend/app/main.py`)
- **Prod:** daily at 04:00 Amsterdam time (scheduled in lifespan)

Manual trigger: `POST /api/admin/scrape` with header `X-Admin-Secret: <value>`

## Known constraints / pitfalls
- `recalculate_all_scores()` is called after every scraper sync — it zeroes and recalculates all totals from scratch. Don't assume `total_points` is incrementally reliable mid-sync.
- `_reset_non_pickers()` in `game_engine.py` is currently a no-op stub — missing picks already reset streaks implicitly through `recalculate_game_scores`. Don't add logic there without understanding the recalc flow.
- `Game.points_base` and `Game.points_multiplier` columns exist but scoring currently uses streak-based logic, not those fields. They're vestigial.
- Player ranking bonuses use `TournamentRankingSnapshot`, not live `Ranking` table — this is intentional (fairness).
- The `Ranking` table holds current PSA global rankings (updated by scraper). `TournamentRankingSnapshot` is frozen at tournament start.

## Adding a new feature — checklist
1. Model changes → `models.py` → migration
2. Schema changes → `schemas.py`
3. Business logic → appropriate service or inline in router (keep routers thin)
4. Router endpoint → `routers/`
5. Register router if new file
6. Frontend: add API call in page component or new page in `pages/`
7. Add route in `App.jsx` if new page
