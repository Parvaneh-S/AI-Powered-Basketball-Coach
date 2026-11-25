"""
Tests that the personal form profile reaches the API and the
coaching agent's tool. Uses the seed database copy set up in
conftest.py (TestPlayer: 3 made, 1 missed).
"""

from fastapi.testclient import TestClient

from backend.app.agent.tools import get_personal_form_profile
from backend.app.api.main import app


client = TestClient(app)


def test_api_returns_the_players_profile():
    response = client.get("/api/players/TestPlayer/form-profile")

    assert response.status_code == 200

    profile = response.json()

    assert profile["player"] == "TestPlayer"
    assert profile["status"] == "insufficient_data"
    assert profile["counts"]["made"] == 3
    assert profile["counts"]["missed"] == 1
    assert "3 made, 1 missed" in profile["message"]


def test_api_unknown_player_has_no_shots():
    response = client.get("/api/players/Nobody/form-profile")

    assert response.status_code == 200
    assert response.json()["counts"]["total_shots"] == 0
    assert response.json()["status"] == "insufficient_data"


def test_agent_tool_returns_the_same_profile():
    tool_profile = get_personal_form_profile("TestPlayer")
    api_profile = client.get(
        "/api/players/TestPlayer/form-profile"
    ).json()

    assert tool_profile == api_profile
