import os
import json
import logging
from flask import Flask, render_template, request
import google.genai as genai
from dotenv import load_dotenv
from datetime import datetime, timezone
import database
from utils import normalize_value, validate_preferences, validate_decision
from flask import jsonify
# from database import get_decision_by_id

load_dotenv()
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("pop")

# Gemini API key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment variables")

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

def get_user_id():
    header_id = request.headers.get("X-User-Id")
    query_id = request.args.get("user_id")
    candidate = header_id or query_id
    if not candidate:
        return 1
    try:
        return int(candidate)
    except Exception:
        return None


def handle_preferences(form):
    preferences = build_preference_object(form)

    is_valid, error = validate_preferences(preferences)
    if not is_valid:
        return False, error or "Invalid preferences"
    
    success = database.save_preferences(preferences)
    if not success:
        return False, "Failed to save preference to database"
    return True, preferences

def clean_gemini_response(text):
    """Removes markdown code fences from Gemini response if present."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:-1]
        text = "\n".join(lines)
    return text

def repair_ai_response(text):
    """Attempt to repair malformed AI JSON. Return JSON string or None."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start:end + 1]

def format_verdict(result):
    verdict_map = {"Yes": "PICK", "No": "PASS", "Maybe": "MAYBE"}
    verdict = verdict_map.get(result.get("verdict"), "MAYBE")
    confidence = result.get("confidence", 0)
    reasoning = result.get("reasoning", "")
    mismatches = result.get("potential_mismatches", [])
    lines = [f"{verdict} (Confidence: {confidence:.2f})\n", "Why:", reasoning]
    lines.append("\nPotential concerns:")
    if mismatches:
        lines.extend([f"- {item}" for item in mismatches])
    else:
        lines.append("- None")
    return "\n".join(lines)

def evaluate_title(title, media_type, preferences):
    """Evaluates a title against user preferences using Gemini AI."""
    likes_str = ", ".join(preferences.get("likes", [])) or "None specified"
    dislikes_str = ", ".join(preferences.get("dislikes", [])) or "None specified"
    prompt = f"""
        You are an assistant that helps someone decide whether a movie or book is worth their time.

        The user is considering the following title:
        Title: "{title}"
        Type: "{media_type}"  (movie or book)

        Here are your preferences:
        - Likes: {likes_str}
        - Dislikes: {dislikes_str}
        - Preferred pace: {preferences.get('pace', 'Not specified')}
        - Emotional tolerance: {preferences.get('emotional_tolerance', 'Not specified')}
        - Goal: {preferences.get('goal', 'Not specified')}

        Your task:
        Evaluate whether the user is likely to enjoy this title.

        Rules:
        - Do NOT include spoilers.
        - Do NOT include fluff or unnecessary commentary.
        - Base your reasoning strictly on the user's preferences.
        - If information about the title is limited, say so clearly.
        - Address the user in the second person point of view ("you")

        OUTPUT FORMAT:
        You MUST respond with a valid JSON object and nothing else.
        Do NOT include markdown.
        Do NOT include explanations outside the JSON.
        There are two possible response types:

        1) If the title is valid and recognizable:
        {{
        "status": "valid",
        "normalized_title": "...",
        "verdict": "Yes" | "No" | "Maybe",
        "confidence": number between 0 and 1,
        "reasoning": a short string explaining the decision,
        "potential_mismatches": an array of short strings (empty if none)
        }}

        2) If the title appears misspelled or ambiguous:
        {{
        "status": "suggestions",
        "suggestions": ["Title 1", "Title 2", ...]
        }}

        If the information is insufficient, return "Maybe" with a lower confidence.

        Respond ONLY with the JSON object.
    """
    # if not GEMINI_API_KEY:
    #     return "Error: GEMINI_API_KEY not configured"
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        if hasattr(response, 'text'):
            return response.text
        if hasattr(response, 'candidates') and response.candidates:
            return response.candidates[0].content.parts[0].text
        return "Error: Unexpected response format from Gemini"
    except Exception as e:
        logger.exception("Error calling Gemini API")
        return f"Error: {str(e)}"


def run_decision_pipeline(raw_prefs, item_name, item_type="movie", user_id=1, profile_id=None):
    # 1. Build and normalize preference object from raw input
    preferences = build_preference_object(raw_prefs)

    # 2. Call your AI function using the cleaned data
    raw_response = evaluate_title(item_name, item_type, preferences)

    # 3. Clean and parse the AI response
    cleaned_response = clean_gemini_response(raw_response)
    try:
        parsed = json.loads(cleaned_response)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse Gemini JSON: %s", e)
        repaired = repair_ai_response(cleaned_response)
        if not repaired:
            return (False, "Invalid JSON structure from AI")
        try:
            parsed = json.loads(repaired)
        except Exception as inner_e:
            logger.warning("Failed to parse repaired JSON: %s", inner_e)
            return (False, "Invalid JSON structure from AI")
    except Exception as e:
        print(f"Unexpected error parsing Gemini JSON: {e}")
        return (False, "AI provider unreachable")

    # Prepare decision dict
    # Handle suggestion-only responses
    if parsed.get("status") == "suggestions":
        suggestions = parsed.get("suggestions", [])
        if isinstance(suggestions, list) and suggestions:
            return (False, {"type": "suggestions", "suggestions": suggestions})
        return (False, "AI returned ambiguous title suggestions")

    confidence = parsed.get("confidence")
    if isinstance(confidence, str):
        try:
            confidence = float(confidence)
        except Exception:
            confidence = None

    decision = {
        "item_title": item_name,
        "item_type": item_type,
        "verdict": parsed.get("verdict"),
        "confidence": confidence,
        "reasoning": parsed.get("reasoning"),
        "potential_mismatches": parsed.get("potential_mismatches"),
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    # 4. Call your validation function on the AI response
    is_valid = validate_decision(decision)

    if not is_valid:
        # Try to give a more specific reason if possible
        return (False, "Validation failed: Decision data did not meet requirements")

    # 5. Call your saving function
    if database.save_decision(decision, user_id=user_id, profile_id=profile_id):
        return (True, decision)
    else:
        return (False, "Failed to save decision to database")

@app.route("/", methods=["GET"])
def home():
    return render_template("index.html")

@app.route("/settings", methods=["GET"])
def settings_page():
    return render_template("preferences.html")

@app.route("/past-decisions", methods=["GET"])
def history_page():
    return render_template("history.html")

@app.route("/preferences", methods=["GET"])
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

        if not item_name or not raw_prefs:
            return api_error("Missing item_name or preferences", status=400)
    
        profile_id = raw_prefs.get("id")
        success, result = run_decision_pipeline(raw_prefs, item_name, item_type, user_id=user_id, profile_id=profile_id)

        if success:
            return api_success(result, status=201)
        if isinstance(result, dict) and result.get("type") == "suggestions":
            return api_error("Ambiguous title", status=400, error_type="suggestions")
        return api_error(result, status=400)
    except Exception:
        logger.exception("Decision handling failed")
        return api_error("Server error evaluating title", status=500, error_type="server_error")
    
@app.route("/preferences", methods=["POST"])
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
        if not username:
            return api_error("username is required", status=400)

        user = database.create_user(username=username, email=email)
        return api_success({"id": user.id, "username": user.username, "email": user.email}, status=201)
    except Exception:
        logger.exception("Failed to create user")
        return api_error("Server error creating user", status=500, error_type="server_error")


@app.route("/profiles", methods=["GET"])
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
