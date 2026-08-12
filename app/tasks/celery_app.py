import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app
from app.extensions import celery

flask_app = create_app()
celery.conf.update(flask_app.config)
celery.conf.broker_url = flask_app.config.get("CELERY_BROKER_URL") or "redis://127.0.0.1:6379/0"
celery.conf.result_backend = flask_app.config.get("CELERY_RESULT_BACKEND") or "redis://127.0.0.1:6379/1"
celery.conf.timezone = "UTC"
celery.conf.enable_utc = True
celery.conf.task_serializer = "json"
celery.conf.accept_content = ["json"]
celery.conf.result_serializer = "json"
celery.conf.include = [
    "app.tasks.system_tasks",
    "app.tasks.mail_tasks",
    "app.tasks.document_tasks",
    "app.tasks.ai_tasks",
    "app.tasks.maintenance_tasks",
]
celery.conf.beat_schedule = {
    "purge-tombstoned-daily": {
        "task": "crimegpt.purge_tombstoned",
        "schedule": 86400.0,
    },
}
if os.name == "nt":
    celery.conf.worker_pool = "solo"


class ContextTask(celery.Task):
    abstract = True

    def __call__(self, *args, **kwargs):
        with flask_app.app_context():
            return self.run(*args, **kwargs)


celery.Task = ContextTask

import app.tasks.ai_tasks  # noqa: E402,F401
import app.tasks.document_tasks  # noqa: E402,F401
import app.tasks.mail_tasks  # noqa: E402,F401
import app.tasks.maintenance_tasks  # noqa: E402,F401
import app.tasks.system_tasks  # noqa: E402,F401
