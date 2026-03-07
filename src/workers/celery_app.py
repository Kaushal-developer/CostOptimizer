"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab
from src.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "costoptimizer",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_soft_time_limit=600,
    task_time_limit=900,
    result_expires=86400,
)

celery_app.conf.task_routes = {
    "src.workers.tasks.sync_cloud_account": {"queue": "ingestion"},
    "src.workers.tasks.run_optimization": {"queue": "optimization"},
    "src.workers.tasks.execute_remediation": {"queue": "remediation"},
    "src.workers.tasks.generate_report": {"queue": "reports"},
}

celery_app.conf.beat_schedule = {
    "sync-all-accounts-daily": {
        "task": "src.workers.tasks.sync_all_accounts",
        "schedule": crontab(hour=2, minute=0),
    },
    "run-optimization-daily": {
        "task": "src.workers.tasks.run_all_optimizations",
        "schedule": crontab(hour=4, minute=0),
    },
    "generate-weekly-reports": {
        "task": "src.workers.tasks.generate_all_reports",
        "schedule": crontab(hour=6, minute=0, day_of_week=1),
    },
}

celery_app.autodiscover_tasks(["src.workers"])
