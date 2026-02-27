import json
import os
import logging
from ai_service import call_gemini_with_retry, clean_gemini_response

logger = logging.getLogger("pop")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")


def build_recommendations_prompt(title, item_type, preferences):
    likes = ", ".join(preferences.get("likes", [])) or "not specified"
    dislikes = ", ".join(preferences.get("dislikes", [])) or "not specified"
    pace = preferences.get("pace") or "any"
    emotional = preferences.get("emotional_tolerance") or "any"
    goal = preferences.get("goal") or "any"

    return f"""You are a {item_type} recommendation engine.

The user just evaluated "{title}" (a {item_type}).

Their preferences:
- Likes: {likes}
- Dislikes: {dislikes}
- Preferred pace: {pace}
- Emotional tolerance: {emotional}
- Goal: {goal}

Recommend exactly 3 {item_type}s this user would enjoy, based strictly on their preferences.
Do NOT recommend "{title}" itself. Choose real, well-known titles only.

Respond ONLY with a valid JSON array — no markdown, no extra text:
[
  {{"title": "Title Name", "reason": "One sentence: why they would enjoy it given their preferences"}},
  {{"title": "Title Name", "reason": "..."}},
  {{"title": "Title Name", "reason": "..."}}
]"""


def get_recommendations(title, item_type, preferences,
                        model="gemini-2.0-flash",
                        timeout_seconds=15, retries=2, backoff_seconds=0.5):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not configured")

    prompt = build_recommendations_prompt(title, item_type, preferences)
    raw = call_gemini_with_retry(
        GEMINI_API_KEY, prompt, model, timeout_seconds, retries, backoff_seconds
    )

    cleaned = clean_gemini_response(raw)

    # Try direct parse
    try:
        result = json.loads(cleaned)
        if isinstance(result, list):
            return result[:3]
    except (json.JSONDecodeError, TypeError):
        pass

    # Try to extract array from surrounding text
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            result = json.loads(cleaned[start:end + 1])
            if isinstance(result, list):
                return result[:3]
        except (json.JSONDecodeError, TypeError):
            pass

    logger.warning("Could not parse recommendations from AI response: %s", cleaned[:200])
    return []
