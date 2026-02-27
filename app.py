import os
import logging
import time
import json as jsonlib
import uuid
from functools import wraps
from flask import Flask, render_template, request, session, redirect, url_for, g
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text
from dotenv import load_dotenv
from datetime import datetime, timezone
import database
from config import DevelopmentConfig, StagingConfig, ProductionConfig
from utils import normalize_value, validate_preferences
from job_queue import get_queue
from jobs import process_decision_job
from reviews import get_reviews
from recommendations import get_recommendations
from flask import jsonify
# from database import get_decision_by_id

load_dotenv()
app = Flask(__name__)

_ENV = os.getenv("APP_ENV", "development").lower()
if _ENV == "production":
    app.config.from_object(ProductionConfig)
elif _ENV == "staging":
    app.config.from_object(StagingConfig)
else:
    app.config.from_object(DevelopmentConfig)

def _build_logger():
    logger = logging.getLogger("pop")
    level = getattr(logging, app.config.get("LOG_LEVEL", "INFO").upper(), logging.INFO)
    logger.setLevel(level)
    handler = logging.StreamHandler()
    if app.config.get("LOG_FORMAT") == "json":
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
    else:
        formatter = logging.Formatter("%(levelname)s %(name)s: %(message)s")
        handler.setFormatter(formatter)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger

logger = _build_logger()
app.secret_key = app.config["SECRET_KEY"]
if app.secret_key == "dev-secret-change-me":
    logger.warning("FLASK_SECRET_KEY not set; using insecure default")

# Gemini API key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment variables")

JOB_QUEUE = get_queue(app.config["REDIS_URL"]) if app.config["ASYNC_ENABLED"] else None

def build_preference_object(form, include_updated_at=True):
    """Builds a cleaned and normalized preference object from form data."""
    preferences = {
        "likes": normalize_value(form.get("likes"), as_list=True),
        "dislikes": normalize_value(form.get("dislikes"), as_list=True),
        "pace": normalize_value(form.get("pace")),
        "emotional_tolerance": normalize_value(form.get("emotional_tolerance")),
        "goal": normalize_value(form.get("goal"))
    }
    if include_updated_at:
        preferences["updated_at"] = datetime.now(timezone.utc).isoformat()
    return preferences

def api_success(data=None, status=200):
    return jsonify({"success": True, "data": data, "error": None}), status

def api_error(message, status=400, error_type="invalid_request"):
    return jsonify({"success": False, "data": None, "error": {"message": message, "type": error_type}}), status

RATE_LIMIT_WINDOW_SECONDS = app.config["RATE_LIMIT_WINDOW_SECONDS"]
RATE_LIMIT_MAX_REQUESTS = app.config["RATE_LIMIT_MAX_REQUESTS"]
_rate_limit_buckets = {}
_metrics = {
    "requests_total": 0,
    "by_path": {},
    "by_status": {},
}

def _log_event(level, payload):
    if app.config.get("LOG_FORMAT") == "json":
        message = jsonlib.dumps(payload, ensure_ascii=False)
        getattr(logger, level)(message)
    else:
        getattr(logger, level)(payload.get("message", "event"))

def _rate_limit_ok(user_id):
    now = time.time()
    bucket = _rate_limit_buckets.get(user_id)
    if not bucket or now - bucket["start"] > RATE_LIMIT_WINDOW_SECONDS:
        _rate_limit_buckets[user_id] = {"start": now, "count": 1}
        return True
    if bucket["count"] >= RATE_LIMIT_MAX_REQUESTS:
        return False
    bucket["count"] += 1
    return True

def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            return api_error("Authentication required", status=401, error_type="unauthorized")
        if not _rate_limit_ok(user_id):
            return api_error("Rate limit exceeded", status=429, error_type="rate_limited")
        return fn(*args, **kwargs)
    return wrapper

def get_user_id():
    return session.get("user_id")


@app.before_request
def _start_request():
    g.request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    g.request_start = time.time()


@app.after_request
def _after_request(response):
    duration_ms = int((time.time() - g.request_start) * 1000) if hasattr(g, "request_start") else None
    response.headers["X-Request-Id"] = g.request_id
    _metrics["requests_total"] += 1
    _metrics["by_path"][request.path] = _metrics["by_path"].get(request.path, 0) + 1
    status_key = str(response.status_code)
    _metrics["by_status"][status_key] = _metrics["by_status"].get(status_key, 0) + 1
    _log_event("info", {
        "event": "request",
        "message": f"{request.method} {request.path} {response.status_code}",
        "request_id": g.request_id,
        "method": request.method,
        "path": request.path,
        "status": response.status_code,
        "duration_ms": duration_ms,
        "user_id": session.get("user_id"),
    })
    return response


def handle_preferences(form):
    preferences = build_preference_object(form)

    is_valid, error = validate_preferences(preferences)
    if not is_valid:
        return False, error or "Invalid preferences"

    user_id = get_user_id()
    if not user_id:
        return False, "Authentication required"

    success = database.save_preferences(preferences, user_id=user_id, profile_name="default")
    if not success:
        return False, "Failed to save preference to database"
    return True, preferences

def _build_job_payload(item_name, item_type, preferences, user_id, profile_id):
    return {
        "item_name": item_name,
        "item_type": item_type,
        "preferences": preferences,
        "user_id": user_id,
        "profile_id": profile_id,
        "api_key": GEMINI_API_KEY,
        "model": "gemini-2.0-flash",
        "timeout_seconds": app.config["AI_TIMEOUT_SECONDS"],
        "retries": app.config["AI_RETRY_COUNT"],
        "backoff_seconds": app.config["AI_RETRY_BACKOFF_SECONDS"],
        "cache_ttl": app.config["CACHE_TTL_SECONDS"],
    }

@app.route("/", methods=["GET"])
def home():
    if not session.get("user_id"):
        return redirect(url_for("register_page"))
    welcome_message = session.pop("welcome_message", None)
    return render_template("index.html", welcome_message=welcome_message)

@app.route("/healthz", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200

@app.route("/readyz", methods=["GET"])
def readiness_check():
    try:
        session_db = database.get_session()
        session_db.execute(text("SELECT 1"))
        session_db.close()
        return jsonify({"status": "ok"}), 200
    except Exception:
        logger.exception("Readiness check failed")
        return jsonify({"status": "error"}), 500

@app.route("/metrics", methods=["GET"])
def metrics():
    return jsonify(_metrics), 200

@app.route("/jobs/<job_id>", methods=["GET"])
@auth_required
def job_status(job_id):
    if not JOB_QUEUE:
        return api_error("Async queue not available", status=400)
    job = JOB_QUEUE.fetch_job(job_id)
    if not job:
        return api_error("Job not found", status=404, error_type="not_found")
    status = job.get_status()
    result = job.result if status == "finished" else None
    return api_success({"status": status, "result": result})

@app.route("/login", methods=["GET"])
def login_page():
    return render_template("login.html")

@app.route("/register", methods=["GET"])
def register_page():
    return render_template("register.html")

@app.route("/settings", methods=["GET"])
def settings_page():
    if not session.get("user_id"):
        return redirect(url_for("register_page"))
    return render_template("preferences.html")

@app.route("/past-decisions", methods=["GET"])
def history_page():
    if not session.get("user_id"):
        return redirect(url_for("register_page"))
    return render_template("history.html")

@app.route("/preferences", methods=["GET"])
@auth_required
def view_preferences():
    try:
        user_id = get_user_id()
        if user_id is None:
            return api_error("Invalid user_id", status=400)
        prefs = database.get_preferences(user_id)
        if not prefs:
            return api_error("No saved preferences", status=404, error_type="not_found")
        return api_success(prefs)
    except Exception:
        logger.exception("Failed to fetch preferences")
        return api_error("Server error fetching preferences", status=500, error_type="server_error")

@app.route("/decide", methods=["POST"])
@auth_required
def handle_decision():
    try:
        data = request.get_json()
        if data is None:
            return api_error("Invalid JSON body", status=400)

        item_name = data.get('item_name')
        item_type = data.get("item_type", "movie")
        user_id = get_user_id()
        if user_id is None:
            return api_error("Invalid user_id", status=400)
        raw_prefs = database.get_preferences(user_id)

        if item_type not in {"movie", "book"}:
            return api_error("Invalid item_type", status=400)

        if not item_name:
            return api_error("Missing item_name", status=400)
        if not raw_prefs:
            return api_error("Please set preferences first.", status=400, error_type="missing_preferences")
    
        profile_id = raw_prefs.get("id")
        payload = _build_job_payload(item_name, item_type, raw_prefs, user_id, profile_id)

        if app.config["ASYNC_ENABLED"] and JOB_QUEUE:
            job = JOB_QUEUE.enqueue(
                process_decision_job,
                payload,
                job_timeout=app.config["AI_TIMEOUT_SECONDS"] + 5,
                result_ttl=3600,
            )
            return api_success({"job_id": job.id, "status_url": f"/jobs/{job.id}"}, status=202)

        result = process_decision_job(payload)
        if result.get("status") == "completed":
            return api_success(result.get("data"), status=201)
        if result.get("status") == "suggestions":
            return api_error("Ambiguous title", status=400, error_type="suggestions")
        return api_error(result.get("message", "Evaluation failed"), status=400)
    except Exception:
        logger.exception("Decision handling failed")
        return api_error("Server error evaluating title", status=500, error_type="server_error")
    
@app.route("/reviews", methods=["GET"])
@auth_required
def reviews():
    try:
        title = request.args.get("title", "").strip()
        item_type = request.args.get("type", "movie").strip()

        if not title:
            return api_error("Missing title parameter", status=400)
        if item_type not in {"movie", "book"}:
            return api_error("Invalid type; must be 'movie' or 'book'", status=400)

        data = get_reviews(title, item_type)
        if data is None:
            return api_error("No review data found", status=404, error_type="not_found")
        return api_success(data)
    except Exception:
        logger.exception("Failed to fetch reviews")
        return api_error("Server error fetching reviews", status=500, error_type="server_error")


@app.route("/recommendations", methods=["GET"])
@auth_required
def recommendations():
    try:
        title = request.args.get("title", "").strip()
        item_type = request.args.get("type", "movie").strip()
        user_id = get_user_id()

        if not title:
            return api_error("Missing title parameter", status=400)
        if item_type not in {"movie", "book"}:
            return api_error("Invalid type; must be 'movie' or 'book'", status=400)
        if user_id is None:
            return api_error("Invalid user_id", status=400)

        prefs = database.get_preferences(user_id)
        if not prefs:
            return api_error("No preferences set", status=400, error_type="missing_preferences")

        recs = get_recommendations(
            title=title,
            item_type=item_type,
            preferences=prefs,
            model="gemini-2.0-flash",
            timeout_seconds=app.config["AI_TIMEOUT_SECONDS"],
            retries=app.config["AI_RETRY_COUNT"],
            backoff_seconds=app.config["AI_RETRY_BACKOFF_SECONDS"],
        )
        return api_success(recs)
    except Exception:
        logger.exception("Failed to fetch recommendations")
        return api_error("Server error fetching recommendations", status=500, error_type="server_error")


@app.route("/preferences", methods=["POST"])
@auth_required
def update_preferences():
    try:
        data = request.get_json()
        if data is None:
            return api_error("Invalid JSON body", status=400)
        preferences = build_preference_object(data)
        user_id = get_user_id()
        if user_id is None:
            return api_error("Invalid user_id", status=400)
        profile_name = data.get("profile_name", "default")

        is_valid, error = validate_preferences(preferences)
        if not is_valid:
            return api_error(error or "Invalid preferences format", status=400)

        database.save_preferences(preferences, user_id=user_id, profile_name=profile_name)
        return api_success({"message": "Preferences updated successfully!"}, status=200)
    except Exception:
        logger.exception("Failed to save preferences")
        return api_error("Server error saving preferences", status=500, error_type="server_error")

@app.route("/preferences", methods=["DELETE"])
@auth_required
def remove_preferences():
    try:
        user_id = get_user_id()
        if user_id is None:
            return api_error("Invalid user_id", status=400)
        deleted = database.delete_preferences(user_id=user_id)
        if not deleted:
            return api_error("No active preferences to delete", status=404, error_type="not_found")
        return api_success({"message": "Preferences deleted"}, status=200)
    except Exception:
        logger.exception("Failed to delete preferences")
        return api_error("Server error deleting preferences", status=500, error_type="server_error")

@app.route('/history', methods=['GET'])
@auth_required
def view_history():
    # Set a reasonable maximum limit
    try:
        user_id = get_user_id()
        if user_id is None:
            return api_error("Invalid user_id", status=400)
        MAX_LIMIT = 50
        limit = request.args.get('limit', default=5, type=int)
        offset = request.args.get('offset', default=0, type=int)
        item_type = request.args.get('type')
        verdict = request.args.get('verdict')
        start = request.args.get('start')
        end = request.args.get('end')
        # Clamp the limit to the maximum allowed
        limit = min(max(limit, 1), MAX_LIMIT)
        offset = max(offset, 0)

        if item_type and item_type not in {"movie", "book"}:
            return api_error("Invalid type filter", status=400)
        if verdict and verdict not in {"Yes", "No", "Maybe"}:
            return api_error("Invalid verdict filter", status=400)

        try:
            start_dt = datetime.fromisoformat(start) if start else None
            end_dt = datetime.fromisoformat(end) if end else None
        except ValueError:
            return api_error("Invalid date filter; use ISO format", status=400)
        decisions, total = database.get_recent_decisions(
            user_id=user_id,
            limit=limit,
            offset=offset,
            item_type=item_type,
            verdict=verdict,
            start=start_dt,
            end=end_dt,
        )
        return api_success({
            "items": decisions,
            "pagination": {"limit": limit, "offset": offset, "total": total}
        })
    except Exception:
        logger.exception("Failed to fetch history")
        return api_error("Server error fetching history", status=500, error_type="server_error")


@app.route("/users", methods=["POST"])
def create_user():
    try:
        data = request.get_json()
        if data is None:
            return api_error("Invalid JSON body", status=400)
        username = data.get("username")
        email = data.get("email")
        password = data.get("password")
        if not username:
            return api_error("username is required", status=400)
        if not password:
            return api_error("password is required", status=400)

        password_hash = database.hash_password(password)
        user = database.create_user(username=username, email=email, password_hash=password_hash)
        return api_success({"id": user.id, "username": user.username, "email": user.email}, status=201)
    except IntegrityError:
        return api_error("Username already exists", status=400)
    except Exception:
        logger.exception("Failed to create user")
        return api_error("Server error creating user", status=500, error_type="server_error")


@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        if data is None:
            return api_error("Invalid JSON body", status=400)
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return api_error("username and password are required", status=400)

        user = database.get_user_by_username(username)
        if not user or not database.verify_password(user.password_hash, password):
            return api_error("Invalid credentials", status=401, error_type="unauthorized")

        is_returning = user.last_login_at is not None
        database.set_last_login(user.id)
        session["user_id"] = user.id
        welcome_message = f"Welcome back {user.username}" if is_returning else f"Welcome {user.username}"
        session["welcome_message"] = welcome_message
        return api_success({"message": "Logged in"}, status=200)
    except Exception:
        logger.exception("Failed to login")
        return api_error("Server error during login", status=500, error_type="server_error")


@app.route("/logout", methods=["GET"])
def logout():
    session.pop("user_id", None)
    return redirect(url_for("login_page"))


@app.route("/profiles", methods=["GET"])
@auth_required
def list_profiles():
    try:
        user_id = get_user_id()
        if user_id is None:
            return api_error("Invalid user_id", status=400)
        profiles = database.list_profiles(user_id)
        return api_success(profiles)
    except Exception:
        logger.exception("Failed to list profiles")
        return api_error("Server error fetching profiles", status=500, error_type="server_error")


@app.route("/profiles", methods=["POST"])
@auth_required
def create_profile():
    try:
        data = request.get_json()
        if data is None:
            return api_error("Invalid JSON body", status=400)
        name = data.get("name")
        if not name:
            return api_error("name is required", status=400)
        user_id = get_user_id()
        if user_id is None:
            return api_error("Invalid user_id", status=400)

        preferences = build_preference_object(data)
        is_valid, error = validate_preferences(preferences)
        if not is_valid:
            return api_error(error or "Invalid preferences format", status=400)

        saved = database.save_preferences(preferences, user_id=user_id, profile_name=name)
        if not saved:
            return api_error("Failed to save profile", status=400)
        return api_success({"message": "Profile created", "name": name}, status=201)
    except Exception:
        logger.exception("Failed to create profile")
        return api_error("Server error creating profile", status=500, error_type="server_error")


@app.route("/profiles/<int:profile_id>/activate", methods=["POST"])
@auth_required
def activate_profile(profile_id):
    try:
        user_id = get_user_id()
        if user_id is None:
            return api_error("Invalid user_id", status=400)
        updated = database.set_active_profile(user_id, profile_id)
        if not updated:
            return api_error("Profile not found", status=404, error_type="not_found")
        return api_success({"message": "Profile activated"}, status=200)
    except Exception:
        logger.exception("Failed to activate profile")
        return api_error("Server error activating profile", status=500, error_type="server_error")
if __name__ == '__main__':
    database.init_db()
    app.run(debug=True)
