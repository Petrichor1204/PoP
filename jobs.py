import hashlib
from datetime import datetime, timezone

import database
from ai_service import evaluate_title, parse_ai_response, build_decision
from utils import validate_decision


def build_cache_key(item_name, item_type, preferences):
    key_source = {
        "item_name": item_name,
        "item_type": item_type,
        "preferences": preferences,
    }
    payload = repr(key_source).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def process_decision_job(payload):
    item_name = payload["item_name"]
    item_type = payload["item_type"]
    preferences = payload["preferences"]
    user_id = payload["user_id"]
    profile_id = payload.get("profile_id")
    api_key = payload["api_key"]
    model = payload["model"]
    timeout_seconds = payload["timeout_seconds"]
    retries = payload["retries"]
    backoff = payload["backoff_seconds"]
    cache_ttl = payload["cache_ttl"]

    if not api_key:
        return {"status": "error", "message": "Missing AI API key"}

    cache_key = build_cache_key(item_name, item_type, preferences)
    now = datetime.now(timezone.utc)
    cached = database.get_ai_cache(cache_key, now)
    if cached:
        decision = build_decision(cached, item_name, item_type)
        if validate_decision(decision):
            database.save_decision(decision, user_id=user_id, profile_id=profile_id)
            return {"status": "completed", "data": decision, "cached": True}

    raw = evaluate_title(
        api_key=api_key,
        title=item_name,
        media_type=item_type,
        preferences=preferences,
        model=model,
        timeout_seconds=timeout_seconds,
        retries=retries,
        backoff_seconds=backoff,
    )
    parsed = parse_ai_response(raw)

    if parsed.get("status") == "suggestions":
        suggestions = parsed.get("suggestions", [])
        return {"status": "suggestions", "suggestions": suggestions}

    decision = build_decision(parsed, item_name, item_type)
    if not validate_decision(decision):
        return {"status": "error", "message": "Validation failed"}

    database.set_ai_cache(cache_key, parsed, now, cache_ttl)
    database.save_decision(decision, user_id=user_id, profile_id=profile_id)
    return {"status": "completed", "data": decision, "cached": False}
