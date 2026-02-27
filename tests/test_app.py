import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import app as app_module
import database as db


@pytest.fixture()
def client(tmp_path, monkeypatch):
    test_db = tmp_path / "test.db"
    monkeypatch.setattr(db, "get_database_url", lambda: f"sqlite:///{test_db}")
    db.init_db()

    app = app_module.app
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def _register_and_login(client):
    res = client.post("/users", json={"username": "tester", "password": "secret"})
    assert res.status_code == 201
    res = client.post("/login", json={"username": "tester", "password": "secret"})
    assert res.status_code == 200


def _set_preferences(client):
    _register_and_login(client)
    payload = {
        "likes": "action, adventure",
        "dislikes": "slow",
        "pace": "fast",
        "emotional_tolerance": "light",
        "goal": "escape",
    }
    return client.post("/preferences", json=payload)


def test_get_preferences_empty(client):
    _register_and_login(client)
    res = client.get("/preferences")
    assert res.status_code == 404
    body = res.get_json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["message"] == "No saved preferences"


def test_set_and_get_preferences(client):
    res = _set_preferences(client)
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["error"] is None

    res = client.get("/preferences")
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["pace"] == "fast"
    assert "updated_at" in body["data"]


def test_preferences_validation(client):
    _register_and_login(client)
    res = client.post("/preferences", json={"likes": "", "dislikes": "", "pace": "", "emotional_tolerance": "", "goal": ""})
    assert res.status_code == 400
    body = res.get_json()
    assert body["success"] is False
    assert body["data"] is None


def test_decide_requires_preferences(client):
    _register_and_login(client)
    res = client.post("/decide", json={"item_name": "Dune", "item_type": "movie"})
    assert res.status_code == 400
    body = res.get_json()
    assert body["success"] is False
    assert body["data"] is None


def test_decide_invalid_item_type(client):
    _set_preferences(client)
    res = client.post("/decide", json={"item_name": "Dune", "item_type": "game"})
    assert res.status_code == 400
    body = res.get_json()
    assert body["success"] is False
    assert body["error"]["message"] == "Invalid item_type"


def test_decide_success(monkeypatch, client):
    _set_preferences(client)

    def fake_evaluate(*args, **kwargs):
        return json.dumps({
            "verdict": "Yes",
            "confidence": 0.8,
            "reasoning": "You like fast-paced adventure.",
            "potential_mismatches": []
        })

    monkeypatch.setattr(app_module, "evaluate_title", fake_evaluate)

    res = client.post("/decide", json={"item_name": "Dune", "item_type": "movie"})
    assert res.status_code == 201
    body = res.get_json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["verdict"] == "Yes"


def test_decide_ai_repair(monkeypatch, client):
    _set_preferences(client)

    def fake_evaluate(*args, **kwargs):
        return "not json"

    def fake_repair(*args, **kwargs):
        return json.dumps({
            "verdict": "Maybe",
            "confidence": "0.3",
            "reasoning": "Limited information.",
            "potential_mismatches": ["Unknown title"]
        })

    monkeypatch.setattr(app_module, "evaluate_title", fake_evaluate)
    monkeypatch.setattr(app_module, "repair_ai_response", fake_repair)

    res = client.post("/decide", json={"item_name": "Unknown", "item_type": "book"})
    assert res.status_code == 201
    body = res.get_json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["verdict"] == "Maybe"


def test_history_pagination_empty(client):
    _register_and_login(client)
    res = client.get("/history?limit=10&offset=0")
    assert res.status_code == 200
    body = res.get_json()
    assert body["success"] is True
    assert body["error"] is None
    assert "items" in body["data"]
    assert "pagination" in body["data"]
    assert body["data"]["pagination"]["limit"] == 10
    assert body["data"]["pagination"]["offset"] == 0


def test_requires_auth(client):
    res = client.get("/preferences")
    assert res.status_code == 401
    body = res.get_json()
    assert body["success"] is False
    assert body["error"]["message"] == "Authentication required"
