from dotenv import load_dotenv

load_dotenv()

from app.tasks.celery_app import celery, flask_app

__all__ = ["celery", "flask_app"]
