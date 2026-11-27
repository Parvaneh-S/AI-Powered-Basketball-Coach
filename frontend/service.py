import os
from urllib.parse import quote

import requests
import streamlit as st


API_URL = os.getenv("SHOTCOACH_API_URL", "http://127.0.0.1:8000").rstrip("/")


def player_url(player_name):
    return f"{API_URL}/api/players/{quote(player_name, safe='')}"


def fetch_player_history(player_name):
    response = requests.get(
        f"{player_url(player_name)}/shots",
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def fetch_recordings(player_name, video_id=None):
    url = f"{player_url(player_name)}/recordings"
    response = requests.get(f"{url}/{quote(video_id, safe='')}" if video_id else url, timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_sessions(player_name):
    response = requests.get(
        f"{player_url(player_name)}/sessions",
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def fetch_session_summary(player_name, session_id):
    response = requests.get(f"{player_url(player_name)}/sessions/{int(session_id)}/summary", timeout=30)
    response.raise_for_status()
    return response.json()


def upload_video(file, player_name, shooting_arm, session_id=None, session_name=None, mode="recording"):
    form_data = {
        "player_name": player_name,
        "shooting_arm": shooting_arm,
    }

    # Without a session ID the backend starts a new session.
    if session_id is not None:
        form_data["session_id"] = str(session_id)
    elif session_name:
        form_data["session_name"] = session_name

    endpoint = {
        "recording": "/api/recordings/upload",
        "single": "/api/shots/upload",
        "multi": "/api/shots/upload-multi",
    }[mode]
    if mode == "recording":
        form_data["background"] = "true"
    response = requests.post(
        f"{API_URL}{endpoint}",
        files={
            "file": (
                file.name,
                file.getvalue(),
                (
                    "video/quicktime"
                    if file.name.lower().endswith(".mov")
                    else "video/mp4"
                ),
            )
        },
        data=form_data,
        timeout=3600,
    )
    response.raise_for_status()
    return response.json()


def fetch_job(job_id):
    response = requests.get(f"{API_URL}/api/jobs/{quote(job_id, safe='')}", timeout=30)
    response.raise_for_status()
    return response.json()


def update_outcome(shot_id, outcome):
    response = requests.patch(
        f"{API_URL}/api/shots/{shot_id}/outcome",
        json={"outcome": outcome},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def ask_coach(player_name, question, selected_shot, history, comparison=None, session_id=None):
    response = requests.post(
        f"{API_URL}/api/coach/ask",
        json={
            "player_name": player_name,
            "question": question,
            "selected_shot_id": selected_shot,
            "session_id": session_id,
            "history": history[-10:],
            "comparison_shot_ids": comparison,
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()


def error_text(error):
    if isinstance(error, requests.exceptions.HTTPError):
        response = error.response
        detail = response.text if response is not None else str(error)
        if response is not None:
            try:
                detail = response.json().get("detail", detail)
            except ValueError:
                pass
        return f"API error: {detail}"
    if isinstance(error, requests.exceptions.Timeout):
        return ("The request timed out. Check the FastAPI "
                "terminal to determine whether processing completed.")
    return "Cannot communicate with FastAPI. Make sure the backend server is running."


def show_request_error(error):
    st.error(error_text(error))


