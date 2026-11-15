from flask import abort, jsonify, redirect, request, url_for
import database as db
from application import LOCAL_USER_ID, read_session_form, required_goal


def register_routes(app):

    @app.get("/timer")
    def timer():
        return redirect(url_for("index") + "#timer-app")

    @app.get("/api/timer")
    def timer_state():
        return jsonify(state=db.get_timer())

    @app.post("/api/timer/<action>")
    def timer_action(action):
        data = request.get_json(silent=True) or {}
        try:
            if action not in {"start", "pause", "resume", "finish", "cancel", "save"}:
                abort(404)
            if action == "save":
                values, error = read_session_form(data)
                if error:
                    raise ValueError(error)
                session_id = db.save_timer(LOCAL_USER_ID, data.get("token"), values)
                return jsonify(saved=True, session_id=session_id)
            goal_id = int(data.get("goal_id") or 0)
            if action == "start":
                required_goal(goal_id)
            state = db.change_timer(action, goal_id, data.get("token"))
            return jsonify(state=state)
        except (ValueError, TypeError) as error:
            return jsonify(error=str(error)), 400
