import json
import time
import concurrent.futures
from datetime import datetime, timezone
import google.genai as genai


def clean_gemini_response(text):
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()[1:-1]
        text = "\n".join(lines)
    return text


def repair_ai_response(text):
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start:end + 1]


def _call_gemini(api_key, prompt, model):
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=model, contents=prompt)
    if hasattr(response, 'text'):
        return response.text
    if hasattr(response, 'candidates') and response.candidates:
        return response.candidates[0].content.parts[0].text
    return "Error: Unexpected response format from Gemini"


def call_gemini_with_retry(api_key, prompt, model, timeout_seconds, retries, backoff_seconds):
    last_error = None
    for attempt in range(retries + 1):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_call_gemini, api_key, prompt, model)
                return future.result(timeout=timeout_seconds)
        except Exception as e:
            last_error = e
            if attempt < retries:
                time.sleep(backoff_seconds * (attempt + 1))
    raise last_error


def build_prompt(title, media_type, preferences):
    likes_str = ", ".join(preferences.get("likes", [])) or "None specified"
    dislikes_str = ", ".join(preferences.get("dislikes", [])) or "None specified"
    return f"""
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


def evaluate_title(api_key, title, media_type, preferences, model, timeout_seconds, retries, backoff_seconds):
    prompt = build_prompt(title, media_type, preferences)
    raw = call_gemini_with_retry(api_key, prompt, model, timeout_seconds, retries, backoff_seconds)
    return raw


def parse_ai_response(raw_response):
    cleaned = clean_gemini_response(raw_response)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        repaired = repair_ai_response(cleaned)
        if not repaired:
            raise ValueError("Invalid JSON structure from AI")
        return json.loads(repaired)


def build_decision(parsed, item_name, item_type):
    confidence = parsed.get("confidence")
    if isinstance(confidence, str):
        try:
            confidence = float(confidence)
        except Exception:
            confidence = None

    return {
        "item_title": item_name,
        "item_type": item_type,
        "verdict": parsed.get("verdict"),
        "confidence": confidence,
        "reasoning": parsed.get("reasoning"),
        "potential_mismatches": parsed.get("potential_mismatches"),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
