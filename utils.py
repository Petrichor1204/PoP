from datetime import datetime

def normalize_value(value, as_list=False):
    if value is None:
        return [] if as_list else None
    normalized = str(value).strip().lower()
    if not normalized:
        return [] if as_list else None
    if as_list:
        return [item.strip() for item in normalized.split(",") if item.strip()]
    return normalized

def validate_preferences(preferences):
    REQUIRED_FIELDS = ["likes", "dislikes", "pace", "emotional_tolerance", "goal", "updated_at"]
    if not preferences:
        return False, "Missing preferences payload"
    for field in REQUIRED_FIELDS:
        if field not in preferences or preferences[field] is None:
            return False, f"Missing required field: {field}"

    if not isinstance(preferences["likes"], list) or not preferences["likes"]:
        return False, "Likes must be a non-empty list"
    if not isinstance(preferences["dislikes"], list) or not preferences["dislikes"]:
        return False, "Dislikes must be a non-empty list"
    for item in preferences["likes"]:
        if not isinstance(item, str) or not item.strip():
            return False, "Likes must contain non-empty strings"
        if len(item.strip()) > 200:
            return False, "Each like must be 200 characters or fewer"
    for item in preferences["dislikes"]:
        if not isinstance(item, str) or not item.strip():
            return False, "Dislikes must contain non-empty strings"
        if len(item.strip()) > 200:
            return False, "Each dislike must be 200 characters or fewer"

    for field in ["pace", "emotional_tolerance", "goal"]:
        if not isinstance(preferences[field], str) or not preferences[field].strip():
            return False, f"{field} must be a non-empty string"

    if not is_valid_timestamp_string(preferences["updated_at"]):
        return False, "updated_at must be a valid ISO timestamp"

    return True, None

def validate_decision(decision):
    """Checks if a decision dict is valid for saving."""
    REQUIRED_FIELDS = [
        "item_title", "item_type", "verdict", "confidence",
        "reasoning", "potential_mismatches", "created_at"
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
    if not is_valid_timestamp_string(decision["created_at"]):
        return False

    # Validate non-empty strings
    for field in ["item_title", "item_type", "reasoning"]:
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

def validate_ai_response(parsed):
    if not isinstance(parsed, dict):
        return False, "AI response must be a JSON object"

    required = {"verdict", "confidence", "reasoning", "potential_mismatches"}
    if set(parsed.keys()) != required:
        return False, "AI response must contain exactly the required keys"

    if parsed["verdict"] not in {"Yes", "No", "Maybe"}:
        return False, "Invalid verdict"

    confidence = parsed["confidence"]
    if isinstance(confidence, str):
        try:
            float(confidence)
        except Exception:
            return False, "Confidence must be a number"
    elif not isinstance(confidence, (int, float)):
        return False, "Confidence must be a number"

    if not isinstance(parsed["reasoning"], str) or not parsed["reasoning"].strip():
        return False, "Reasoning must be a non-empty string"

    if not isinstance(parsed["potential_mismatches"], list):
        return False, "potential_mismatches must be a list"
    for item in parsed["potential_mismatches"]:
        if not isinstance(item, str) or not item.strip():
            return False, "potential_mismatches must be a list of strings"

    return True, None
