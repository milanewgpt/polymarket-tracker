# Polymarket Tweet Tracker Bot

Telegram bot that tracks a weekly Polymarket event of the type  
*"How many tweets will Elon Musk make …"*.

## Architecture

```
polymarket-tracker/
├── main.py               # async entry point
├── config/settings.py    # pydantic-settings from .env
├── domain/               # pure business logic, no I/O
│   ├── entities.py       # dataclasses & enums
│   ├── range_utils.py    # range parsing & lookup
│   └── decision_engine.py# transition rules, fully testable
├── db/                   # SQLAlchemy 2.0 async models + repository
│   ├── models.py
│   ├── session.py
│   └── repository.py
├── clients/              # external HTTP adapters
│   ├── polymarket.py     # Gamma API → event/market parsing
│   └── xtracker.py       # tweet-count extraction (fragile)
├── services/             # orchestration
│   ├── monitoring.py     # main poll-decide-update-notify loop
│   └── notification.py   # Telegram message sending
├── bot/                  # aiogram handlers
│   ├── handlers.py
│   └── formatters.py
├── scheduler/jobs.py     # APScheduler wiring
└── tests/                # pytest unit tests for domain layer
```

### Key design decisions

| Concern | Decision |
|---------|----------|
| Framework | aiogram 3.x (async-first) |
| Scheduler | APScheduler `AsyncIOScheduler` |
| Database | SQLite via `aiosqlite` + SQLAlchemy 2.0 async |
| HTTP | httpx async client |
| Business logic | Pure functions in `domain/` — zero I/O, easy to unit-test |

## Quick start

```bash
# Clone & enter
cd polymarket-tracker

# Create virtualenv
python3 -m venv venv
source venv/bin/activate

# Install deps
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env — set TELEGRAM_BOT_TOKEN at minimum

# Run
python main.py
```

## Running tests

```bash
cd polymarket-tracker
python -m pytest tests/ -v
```

## Telegram commands

| Command | Description |
|---------|-------------|
| `/start` | Show help |
| `/add <url>` | Add a Polymarket weekly event URL |
| `/delete` | Remove the active event |
| `/list` | Show all tracked events |
| `/status` | Detailed status of active event |
| `/count` | Quick tweet count & range |
| `/mute` | Silence notifications (monitoring continues) |
| `/unmute` | Re-enable notifications |
| `/buffer_on` | Enable upward buffer |
| `/buffer_off` | Disable upward buffer |
| `/buffer_value <n>` | Set buffer percentage |
| `/history` | Last 10 transitions |

## Deployment on Ubuntu

```bash
# System deps
sudo apt update && sudo apt install -y python3.11 python3.11-venv

# App directory
sudo mkdir -p /opt/polymarket-tracker
sudo cp -r . /opt/polymarket-tracker/
cd /opt/polymarket-tracker

# Virtualenv & deps
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Config
cp .env.example .env
nano .env   # set TELEGRAM_BOT_TOKEN

# Systemd service
sudo cp polymarket_tracker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now polymarket_tracker
sudo journalctl -u polymarket_tracker -f
```

## Mute behaviour

When muted:
- Polling continues on schedule
- State updates (factual range, notified range) still happen
- Transition logic runs and the `notified_range` updates internally
- Transition events are logged to `notifications_log` with a `[muted]` prefix
- **No outgoing Telegram messages** are sent

This prevents stale "catch-up" alerts on unmute.

## Fragile external integrations

### Xtracker (`clients/xtracker.py`)

The tweet-count source at `xtracker.polymarket.com` has **no documented API**.
Three extraction strategies are tried in order:

1. `/api/user/elonmusk` (guessed REST endpoint)
2. `__NEXT_DATA__` JSON blob in SSR HTML (Next.js pattern)
3. DOM scraping via CSS selectors

**If the site changes:** update the strategy list, JSON field names, or CSS
selectors in `XtrackerClient`. The adapter is fully isolated from business logic.

### Polymarket Gamma API (`clients/polymarket.py`)

Uses `https://gamma-api.polymarket.com/events?slug=…`.

**If the API changes:** update `fetch_event_data` / `parse_event`. The URL
is configurable via `POLYMARKET_GAMMA_API_URL`.

Both clients are behind adapter classes — the rest of the codebase never
touches HTTP directly.
