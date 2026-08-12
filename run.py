import os

from dotenv import load_dotenv

load_dotenv()

from app import create_app, prepare_runtime

app = create_app()

if __name__ == "__main__":
    with app.app_context():
        prepare_runtime(app)
    debug = (os.environ.get("FLASK_ENV") or "development").lower() in ("development", "dev")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=debug, use_reloader=False)
