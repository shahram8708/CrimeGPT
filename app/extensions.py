from celery import Celery, Task
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
cache = Cache()
limiter = Limiter(key_func=get_remote_address, default_limits=[], storage_uri="memory://")
celery = Celery("crimegpt")


class FlaskTask(Task):
    abstract = True

    def __call__(self, *args, **kwargs):
        from flask import current_app

        if current_app:
            return self.run(*args, **kwargs)
        from app import create_app

        app = create_app()
        with app.app_context():
            return self.run(*args, **kwargs)


def init_celery(app):
    celery.conf.update(
        broker_url=app.config.get("CELERY_BROKER_URL", "memory://"),
        result_backend=app.config.get("CELERY_RESULT_BACKEND", "cache+memory://"),
        task_ignore_result=False,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
        task_always_eager=False,
    )
    celery.Task = FlaskTask
    celery.conf.update(app.config)
    return celery
