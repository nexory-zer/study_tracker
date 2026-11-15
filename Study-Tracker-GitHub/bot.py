"""Run the local Study Tracker server."""
import os

from application import app
from routes import register_routes

register_routes(app)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("STUDY_TRACKER_PORT", 5000)))
