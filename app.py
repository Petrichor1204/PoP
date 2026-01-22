import os
import json
from flask import Flask, render_template, request
import google.genai as genai
from dotenv import load_dotenv
from datetime import datetime, timezone
import sqlite3

load_dotenv()
app = Flask(__name__)

# Gemini API key
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment variables")

def normalize_value(value, as_list=False):
    """Normalize a string value: strip whitespace, convert to lowercase. Optionally split comma-separated values into a list."""
    if value is None:
        return [] if as_list else None
    normalized = str(value).strip().lower()
    if not normalized:
        return [] if as_list else None
    if as_list:
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return normalized

def build_preference_object(form):
    """Builds a cleaned and normalized preference object from form data."""
    return {
        "likes": normalize_value(form.get("likes"), as_list=True),
        "dislikes": normalize_value(form.get("dislikes"), as_list=True),
        "pace": normalize_value(form.get("pace")),
        "emotional_tolerance": normalize_value(form.get("emotional_tolerance")),
        "goal": normalize_value(form.get("goal"))
    }
    


def evaluate_title(title, media_type, preferences):
    """Evaluates a title against user preferences using Gemini AI."""
    likes_str = ", ".join(preferences.get("likes", [])) or "None specified"
    dislikes_str = ", ".join(preferences.get("dislikes", [])) or "None specified"
    prompt = f"""
You are an assistant that helps someone decide whether a movie or book is worth their time.

The user are considering the following title:
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

The JSON object MUST have exactly these fields:
- verdict: one of "Yes", "No", or "Maybe"
- confidence: a number between 0 and 1
- reasoning: a short string explaining the decision
- potential_mismatches: an array of short strings (empty if none)

If the information is insufficient, return "Maybe" with a lower confidence.

Respond ONLY with the JSON object.
"""
    if not GEMINI_API_KEY:
        return "Error: GEMINI_API_KEY not configured"
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
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

@app.route("/", methods=["GET", "POST"])
def preferences():
    gemini_response = None
    evaluated_title = None
    if request.method == "POST":
        user_preferences = build_preference_object(request.form)
        evaluated_title = "Cinderella"
        media_type = "movie"
        raw_response = evaluate_title(evaluated_title, media_type, user_preferences)
        cleaned_response = clean_gemini_response(raw_response)
        try:
            parsed = json.loads(cleaned_response)
        except Exception as e:
            print(f"Failed to parse Gemini JSON: {e}")
            parsed = {}
        gemini_response = format_verdict(parsed)
        decision = {
        "title": evaluated_title,
        "media_type": media_type,
        "verdict": parsed["verdict"],
        "confidence": parsed["confidence"],
        "reasoning": parsed["reasoning"],
        "potential_mismatches": parsed["potential_mismatches"],
        "timestamp": datetime.now(timezone.utc).isoformat()
        }
        save_decision(decision)
    return render_template("index.html", gemini_response=gemini_response, evaluated_title=evaluated_title)

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


def load_history(filepath="data/history.json"):
    if not os.path.exists(filepath):
        return []

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []

# def save_decision(decision, filepath="data/history.json"):
#     history = load_history(filepath)
#     history.append(decision)

#     with open(filepath, "w", encoding="utf-8") as f:
#         json.dump(history, f, indent=2)
def validate_decision(decision):
    """Checks if a decision dict is valid for saving."""
    REQUIRED_FIELDS = [
        "title", "media_type", "verdict", "confidence",
        "reasoning", "potential_mismatches", "timestamp"
    ]

    # Check required fields
    if not all(field in decision for field in REQUIRED_FIELDS):
        return False

    # Validate confidence
    confidence = decision["confidence"]
    if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
        return False

    # Validate verdict
    if decision["verdict"] not in {"Yes", "No", "Maybe"}:
        return False

    # Validate timestamp
    if not is_valid_timestamp_string(decision["timestamp"]):
        return False

    # Validate non-empty strings
    for field in ["title", "media_type", "reasoning"]:
        if not isinstance(decision[field], str) or not decision[field].strip():
            return False

    # Validate mismatches is a list
    if not isinstance(decision["potential_mismatches"], list):
        return False

    return True

def is_valid_timestamp_string(timestamp_str):
    try:
        datetime.fromisoformat(timestamp_str)
        return True
    except ValueError:
        return False

def init_db():
    conn = sqlite3.connect('my_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_title TEXT,
            item_type TEXT,
            verdict TEXT,
            confidence REAL,
            reasoning TEXT,
            potential_mismatches TEXT,
            created_at TEXT
        )
    ''')
    conn.commit()
    conn.close()


def save_decision(decision):
    """Validate and save a decision to the SQLite database using a transaction."""
    if not validate_decision(decision):
        print("Decision is invalid, not saving.")
        return False

    try:
        conn = sqlite3.connect('my_database.db')
        cursor = conn.cursor()
        # Serialize potential_mismatches to JSON string
        mismatches_json = json.dumps(decision["potential_mismatches"], ensure_ascii=False)
        with conn:
            cursor.execute(
                '''
                INSERT INTO decisions (
                    item_title, item_type, verdict, confidence, reasoning, potential_mismatches, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    decision["title"],
                    decision["media_type"],
                    decision["verdict"],
                    decision["confidence"],
                    decision["reasoning"],
                    mismatches_json,
                    decision["timestamp"]
                )
            )
        return True
    except Exception as e:
        print(f"Error saving decision: {e}")
        return False
    finally:
        conn.close()

@app.route("/history")
def history():
    conn = sqlite3.connect('my_database.db')
    cursor = conn.cursor()
    cursor.execute('SELECT item_title, item_type, verdict, confidence, reasoning, potential_mismatches, created_at FROM decisions')
    rows = cursor.fetchall()
    decisions = []
    for row in rows:
        decisions.append({
            "title": row[0],
            "media_type": row[1],
            "verdict": row[2],
            "confidence": row[3],
            "reasoning": row[4],
            "potential_mismatches": json.loads(row[5]),
            "timestamp": row[6]
        })
    conn.close()
    return render_template("history.html", decisions=decisions)


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
