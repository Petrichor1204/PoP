import os
import json
from flask import Flask, render_template, request
import google.genai as genai
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# Configure Gemini API
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    print("Warning: GEMINI_API_KEY not found in environment variables")

def build_preference_object(form):
    """
    Builds a cleaned and normalized preference object from form data.
    Normalizes string values by stripping whitespace and converting to lowercase.
    Splits comma-separated genres into lists.
    
    Args:
        form: Flask request.form object
        
    Returns:
        dict: Cleaned preference dictionary with normalized string values
    """
    def normalize_value(value, as_list=False):
        """Normalize a string value: strip whitespace, convert to lowercase.
        Optionally split comma-separated values into a list."""
        if value is None:
            return [] if as_list else None
        # Convert to string, strip whitespace, convert to lowercase
        normalized = str(value).strip().lower()
        if not normalized:
            return [] if as_list else None
        
        if as_list:
            # Split by comma, strip each item, and filter out empty strings
            return [item.strip() for item in normalized.split(",") if item.strip()]
        else:
            return normalized
    
    preferences = {
        "likes": normalize_value(form.get("likes"), as_list=True),
        "dislikes": normalize_value(form.get("dislikes"), as_list=True),
        "pace": normalize_value(form.get("pace")),
        "emotional_tolerance": normalize_value(form.get("emotional_tolerance")),
        "goal": normalize_value(form.get("goal"))
    }
    
    return preferences

def evaluate_title(title, media_type, preferences):
    """
    Evaluates a title (movie or book) against user preferences using Gemini.
    
    Args:
        title: The title to evaluate
        media_type: "movie" or "book"
        preferences: Dictionary with user preferences
        
    Returns:
        Gemini's response as a string
    """
    # Hardcoded title for testing
    # title = "Oliver Twist"
    # media_type = "book"
    
    # Format preferences for the prompt
    likes_str = ", ".join(preferences.get("likes", [])) if preferences.get("likes") else "None specified"
    dislikes_str = ", ".join(preferences.get("dislikes", [])) if preferences.get("dislikes") else "None specified"
    
    prompt = f"""You are an assistant that helps someone decide whether a movie or book is worth their time.

You are considering the following title:
Title: "{title}"
Type: "{media_type}"  (movie or book)

Here are your preferences:
- Likes: {likes_str}
- Dislikes: {dislikes_str}
- Preferred pace: {preferences.get("pace", "Not specified")}
- Emotional tolerance: {preferences.get("emotional_tolerance", "Not specified")}
- Goal: {preferences.get("goal", "Not specified")}

Your task:
Evaluate whether you are likely to enjoy this title.

Rules:
- Do NOT include spoilers.
- Do NOT include fluff or unnecessary commentary.
- Base your reasoning strictly on the user's preferences.
- If information about the title is limited, say so clearly.

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
    
    # Initialize Gemini client and model
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
        elif hasattr(response, 'candidates') and response.candidates:
            return response.candidates[0].content.parts[0].text
        else:
            print(f"Unexpected response format: {response}")
            return f"Error: Unexpected response format from Gemini"
    except Exception as e:
        print(f"Error calling Gemini API: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return f"Error: {str(e)}"

@app.route("/", methods=["GET", "POST"])
def preferences():
    gemini_response = None
    evaluated_title = None
    if request.method == "POST":
        # Build cleaned and normalized preference object
        user_preferences = build_preference_object(request.form)
        
        print(user_preferences)  # proof it works
        
        # Evaluate the title with Gemini
        evaluated_title = "Hustle"
        gemini_response = evaluate_title(evaluated_title, "movie", user_preferences)
        gemini_response = clean_gemini_response(gemini_response)
        try:
            parsed = json.loads(gemini_response)
        except Exception as e:
            print(f"Failed to parse Gemini JSON: {e}")
            parsed = {}
        gemini_response = format_verdict(parsed)
        print(f"Gemini Response: {gemini_response}")
    
    return render_template("index.html", gemini_response=gemini_response, evaluated_title=evaluated_title)

def clean_gemini_response(text):
    """
    Removes markdown code fences from a Gemini response if present.
    Returns a clean JSON string.
    """
    if text is None:
        return None
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()
        # Remove first and last fence lines
        lines = lines[1:-1]
        text = "\n".join(lines)

    return text

def format_verdict(result):
    verdict_map = {
        "Yes": "PICK",
        "No": "PASS",
        "Maybe": "MAYBE"
    }

    verdict = verdict_map.get(result.get("verdict"), "MAYBE")
    confidence = result.get("confidence", 0)
    reasoning = result.get("reasoning", "")
    mismatches = result.get("potential_mismatches", [])

    lines = []
    lines.append(f"{verdict} (Confidence: {confidence:.2f})\n")
    lines.append("Why:")
    lines.append(reasoning)

    if mismatches:
        lines.append("\nPotential concerns:")
        for item in mismatches:
            lines.append(f"- {item}")
    else:
        lines.append("\nPotential concerns:")
        lines.append("- None")

    return "\n".join(lines)


if __name__ == '__main__':
    app.run(debug=True)
