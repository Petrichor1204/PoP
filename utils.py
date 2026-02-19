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
    REQUIRED_FIELDS = ["likes", "dislikes", "pace", "emotional_tolerance", "goal"]
    if not preferences: return False
    for field in REQUIRED_FIELDS:
        if field not in preferences or preferences[field] is None:
            return False
    return True

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
