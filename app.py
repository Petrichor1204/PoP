import os
import json
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

# Gemini API key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment variables")

def build_preference_object(form):
    """Builds a cleaned and normalized preference object from form data."""
    return {
        "likes": normalize_value(form.get("likes"), as_list=True),
        "dislikes": normalize_value(form.get("dislikes"), as_list=True),
        "pace": normalize_value(form.get("pace")),
        "emotional_tolerance": normalize_value(form.get("emotional_tolerance")),
        "goal": normalize_value(form.get("goal"))
    }


def handle_preferences(form):
    preferences = build_preference_object(form)

    if not validate_preferences(preferences):
        return False, "Invalid preferences"
    
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
        {
        "status": "valid",
        "normalized_title": "...",
        "verdict": "Yes" | "No" | "Maybe",
        "confidence": number between 0 and 1,
        "reasoning": a short string explaining the decision,
        "potential_mismatches": an array of short strings (empty if none)
        }

        2) If the title appears misspelled or ambiguous:
        {
        "status": "suggestions",
        "suggestions": ["Title 1", "Title 2", ...]
        }

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
        print(f"Error calling Gemini API: {type(e).__name__}: {e}")
        return f"Error: {str(e)}"


def run_decision_pipeline(raw_prefs, item_name, item_type="movie"):
    # 1. Build and normalize preference object from raw input
    preferences = build_preference_object(raw_prefs)

    # 2. Call your AI function using the cleaned data
    raw_response = evaluate_title(item_name, item_type, preferences)

    # 3. Clean and parse the AI response
    cleaned_response = clean_gemini_response(raw_response)
    try:
        parsed = json.loads(cleaned_response)
    except json.JSONDecodeError as e:
        print(f"Failed to parse Gemini JSON: {e}")
        return (False, "Invalid JSON structure from AI")
    except Exception as e:
        print(f"Unexpected error parsing Gemini JSON: {e}")
        return (False, "AI provider unreachable")

    # Prepare decision dict
    decision = {
        "item_title": item_name,
        "item_type": item_type,
        "verdict": parsed.get("verdict"),
        "confidence": parsed.get("confidence"),
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
    if database.save_decision(decision):
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
    prefs = database.get_preferences()
    return jsonify(prefs)

@app.route("/decide", methods=["POST"])
def handle_decision():
    data = request.get_json()

    item_name = data.get('item_name')
    item_type = data.get("item_type", "movie")
    raw_prefs = database.get_preferences()

    if not item_name or not raw_prefs:
        return jsonify({"error": "Missing item_name or preferences"}), 400
    
    success, result = run_decision_pipeline(raw_prefs, item_name, item_type)

    if success:
        return jsonify({"success": True, "data": result}), 201
    else:
        return jsonify({"success": False, "message": result}), 400
    
@app.route("/preferences", methods=["POST"])
def update_preferences():
    data = request.get_json()
    preferences = build_preference_object(data)

    if not validate_preferences(preferences):
        return jsonify({"success": False, "message": "Invalid preferences format"}), 400

    preferences["updated_at"] = datetime.now(timezone.utc).isoformat()

    database.save_preferences(preferences)
    return jsonify({"success": True, "message": "Preferences updated successfully!"})

@app.route("/preferences", methods=["DELETE"])
def remove_preferences():
    database.delete_preferences()
    return jsonify({"message": "Preferences deleted"})

@app.route('/history', methods=['GET'])
def view_history():
    # Set a reasonable maximum limit
    MAX_LIMIT = 50
    limit = request.args.get('limit', default=5, type=int)
    # Clamp the limit to the maximum allowed
    limit = min(max(limit, 1), MAX_LIMIT)
    decisions = database.get_recent_decisions(limit)
    return jsonify(decisions)

if __name__ == '__main__':
    database.init_db()
    app.run(debug=True)
