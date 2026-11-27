"""
Tests that the personal form profile reaches the API and the
active coaching retrieval layer. Uses the seed database copy set up in
conftest.py (TestPlayer: 3 made, 1 missed).
"""

from fastapi.testclient import TestClient

from backend.app.agent.context import EvidenceContext
from backend.app.agent.memory import empty_memory
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


def test_agent_tool_returns_the_owned_profile():
    context = EvidenceContext("TestPlayer", "How can I improve my shot?", None, (), [], empty_memory())
    profile = context.retrieve_profile()
    assert profile["status"] == "insufficient_data"
    assert profile["counts"]["made"] == 3
    assert profile["counts"]["missed"] == 1
    assert profile["sample_shots"] == 4

    unknown = EvidenceContext("Nobody", "How can I improve my shot?", None, (), [], empty_memory())
    assert unknown.retrieve_profile()["counts"]["total_shots"] == 0
