"""The apps listed when the portal starts with an empty catalog. Admins edit the catalog in
the app afterwards (Admin > Apps); this list is only used once."""
from __future__ import annotations

SEED_APPS = [
    {"id": "sepa", "name": "SEPA Strategy", "order": 1,
     "description": "Minervini SEPA stock scans, paper trading and backtests, plus the McMillan "
                    "options screener (covered calls, cash-secured puts, implied volatility).",
     "url": "https://sepa-web-t7d3owg44a-ue.a.run.app", "project": "vahxa-trade-markm"},
    {"id": "stock-screener", "name": "Stock Screener", "order": 2,
     "description": "Trading dashboard and stock screener.",
     "url": "https://vahxa-trade-public-vk44cnj6wq-uc.a.run.app", "project": "vahxa-research-504217"},
    {"id": "family-aid", "name": "Family AI Assistant", "order": 3,
     "description": "AI family scheduling and planning: daily schedules, study plans, Google "
                    "Calendar sync and weekly reports.",
     "url": "https://family-aid-frontend-6wx42j46eq-uc.a.run.app", "project": "vahxa-home"},
    {"id": "student", "name": "Student AI Assistant", "order": 4,
     "description": "AI planner for a student: activities, subjects, deadlines, daily and weekly "
                    "schedules and reminders.",
     "url": "https://vahxa-student-mposqy6mjq-uc.a.run.app", "project": "vahxa-student"},
]


def seed(store) -> None:
    """Add SEED_APPS the first time the portal runs (never again, even if admins delete them)."""
    if store.get_meta("seeded"):
        return
    if not store.list_apps():
        for app in SEED_APPS:
            store.put_app(dict(app))
    store.set_meta("seeded", True)
