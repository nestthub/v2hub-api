from __future__ import annotations

from celery import Celery

from src.core.config import settings

app = Celery(
    "v2hubapi",
    broker=settings.redis_url_str,
    backend=settings.redis_url_str,
    include=["worker.tasks.refresh_external"],
)

app.conf.update(
    # ── Serialisation ──────────────────────────────────────────────────────
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # ── Timezone ───────────────────────────────────────────────────────────
    timezone="UTC",
    enable_utc=True,
    # ── Beat schedule: refresh all external subscriptions every 15 min ────
    beat_schedule={
        "refresh-all-external-urls": {
            "task": "worker.tasks.refresh_external.refresh_all_external_urls",
            "schedule": 900.0,  # 900 seconds = 15 minutes
            "options": {"expires": 870},  # Expire before next run
        },
    },
    # ── Reliability ────────────────────────────────────────────────────────
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # ── Result expiry (we don't use results, but keep low for safety) ──────
    result_expires=300,
)
