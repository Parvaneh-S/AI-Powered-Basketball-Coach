import re
from pathlib import Path
from time import sleep

import requests
import streamlit as st

from frontend.coach_tabs import PANELS, render_coach_page
from frontend.service import (
    API_URL,
    fetch_job,
    fetch_recordings,
    fetch_sessions,
    player_url,
    show_request_error,
    update_outcome,
    upload_video,
)
from frontend.session_detail import render_form_analysis, render_recording


PAGES = {
    "home": ("Home", ":material/home:"),
    "sessions": ("Sessions", ":material/video_library:"),
    "coach": ("Coach", ":material/chat_bubble:"),
    "progress": ("Progress", ":material/monitoring:"),
}
NO_SESSION = 0
st.set_page_config(page_title="ShotCoach", page_icon="🏀", layout="wide", initial_sidebar_state="collapsed")
st.session_state.setdefault("player_name", st.query_params.get("player", "TestPlayer"))
st.session_state.setdefault("player_selector", st.session_state.player_name)
st.session_state.setdefault("messages", [])
st.session_state.setdefault("coach_session", None)
st.session_state.setdefault("coach_recording", None)


def go(page, session=None, recording=None):
    params = {"page": page}
    if session is not None:
        params["session"] = str(session)
    if recording is not None:
        params["recording"] = recording
    st.query_params.from_dict(params)


def continue_coaching():
    go("coach", st.session_state.coach_session, st.session_state.coach_recording)
    if attempt := st.session_state.get("coach_attempt"):
        st.query_params["attempt"] = attempt


def change_player():
    player = st.session_state.player_selector.strip()
    if player == st.session_state.player_name:
        return
    st.session_state.player_name = player
    st.session_state.messages = []
    st.session_state.pop("pending_question", None)
    st.session_state.coach_session = None
    st.session_state.coach_recording = None
    st.session_state.pop("coach_attempt", None)
    for key in (*PANELS.values(), "practice_saved", "practice_error"):
        st.session_state.pop(key, None)
    st.session_state.pop("upload_complete", None)
    st.session_state.pop("clip_results", None)
    current = st.query_params.get("page", "home")
    go("sessions" if current == "session" else current)


def session_name(session):
    return session.get("name") or f"Practice session {session['session_id']}"


def date_label(session):
    return session["date"] or "Date unavailable"


def accuracy_label(session):
    value = session.get("accuracy_pct")
    return f"{value:g}%" if value is not None else "Unavailable"


def recording_label(recording):
    return recording["name"] or recording["video_id"]


def session_cards(sessions, key):
    with st.container(key=f"session_list_{key}"):
        for session in sessions:
            name_column, action_column = st.columns([3, 1.3], vertical_alignment="center")
            name = session_name(session)
            name_column.markdown("**" + name + "**")
            count = session["shot_count"]
            summary = f"{date_label(session)} · {count} {'attempt' if count == 1 else 'attempts'}"
            if count:
                made, missed, unknown = (session.get(field) for field in ("made", "missed", "unknown"))
                if None in (made, missed, unknown):
                    summary += " · Outcome counts unavailable"
                else:
                    summary += f" · {made} made · {missed} missed"
                    if unknown:
                        summary += f" · {unknown} unknown"
            name_column.caption(summary)
            action_column.button(f"Open {name}", key=f"{key}_{session['session_id']}", type="tertiary",
                                 icon=":material/arrow_forward:", icon_position="right",
                                 on_click=go, args=("session", session["session_id"]))


def home_page(sessions):
    with st.container(key="practice_hero"):
        st.title("Ready for your next practice?", anchor=False)
        st.write("Upload a recording to review your shooting form and get feedback from your coach.")
        st.button("Upload video", type="primary", icon=":material/upload:", on_click=go, args=("upload",))

    st.subheader("Practice history")
    if sessions:
        with st.container(key="practice_overview"):
            first, second, third = st.columns(3)
            first.metric("Sessions", len(sessions))
            second.metric("Detected attempts", sum(item["shot_count"] for item in sessions))
            third.metric("Latest session accuracy", accuracy_label(sessions[0]), help="Uses known outcomes only.")
        st.subheader("Recent sessions")
        session_cards(sessions[:3], "recent")
        if len(sessions) > 3:
            st.button("View all sessions", on_click=go, args=("sessions",))
    else:
        st.info("Your practice sessions will appear here after your first analysis.")

    st.divider()
    st.button("Open AI coach", icon=":material/chat_bubble:", on_click=continue_coaching)


def upload_page(player, sessions):
    st.button("Back to sessions", type="tertiary", icon=":material/arrow_back:", on_click=go, args=("sessions",))
    st.title("New practice recording")
    if job_id := st.query_params.get("job"):
        follow_upload_job(player, job_id)
        return
    with st.container(key="recording_upload"):
        file = st.file_uploader("Upload your basketball recording", type=["mp4", "mov"],
                                help="Drag and drop or browse for an MP4 or MOV. Maximum file size is 1 GB.",
                                key=f"upload_file_{player}_{st.session_state.get('upload_revision', 0)}")
    if file is not None:
        st.video(file, format="video/quicktime" if file.name.lower().endswith(".mov") else "video/mp4")
        if file.name.lower().endswith(".mov"):
            st.caption("MOV preview depends on your browser. ShotCoach checks and converts the file during analysis.")
    with st.container(key="recording_tips"):
        st.subheader("Recording tips")
        st.write("Use a stable side-view camera. Keep your whole body, the ball, and the hoop in frame.")

    names = {item["session_id"]: f"{session_name(item)} · {date_label(item)}" for item in sessions}
    target = st.selectbox("Practice session", [NO_SESSION, *names],
                          format_func=lambda value: names.get(value, "Start a new session"),
                          key=f"upload_session_{player}") or None
    name = st.text_input("Session name (optional)", max_chars=100, key=f"upload_name_{player}") if target is None else None
    arm = st.selectbox("Shooting arm", ["right", "left"], format_func=str.capitalize)
    modes = {
        "recording": "Full recording with session coaching",
        "single": "One shot",
        "multi": "Several shots (separate clips)",
    }
    mode = st.radio("Analysis mode", list(modes), format_func=modes.__getitem__)
    if not st.button("Analyze recording", type="primary", icon=":material/play_arrow:"):
        return
    if file is None:
        st.warning("Select a video to analyze.")
        return
    if file.size > 1024 * 1024 * 1024:
        st.error("The maximum upload size is 1 GB.")
        return
    try:
        message = "Analyzing your shot" if mode == "single" else "Uploading your recording"
        with st.spinner(message, show_time=True):
            result = upload_video(file, player, arm, target, name.strip() if name else None, mode)
        if "job_id" in result:
            st.query_params.from_dict({"page": "upload", "job": result["job_id"], "player": player})
            st.rerun()
        session_id, video_id = result["session_id"], result["video_id"]
    except requests.RequestException as error:
        show_request_error(error)
        return
    except (KeyError, TypeError, ValueError):
        st.error("The upload returned an unexpected result. Check Sessions for the recording.")
        return

    open_uploaded_session(player, session_id, video_id)


def open_uploaded_session(player, session_id, video_id):
    st.session_state.upload_revision = st.session_state.get("upload_revision", 0) + 1
    st.session_state.upload_complete = (player, session_id, video_id)
    go("session", session_id, video_id)
    st.rerun()


def follow_upload_job(player, job_id):
    progress = st.progress(0, text="Starting analysis")
    try:
        while True:
            job = fetch_job(job_id)
            if job["player_name"] != player:
                st.info("This analysis belongs to another player.")
                return
            total = job.get("total") or 0
            done = job.get("done") or 0
            stage = job["stage"]
            if total and job.get("mode") == "recording":
                stage = f"{stage} ({done:,} of {total:,} frames)"
            progress.progress(min(done / total, 1.0) if total else 0, text=stage)
            if job["status"] == "failed":
                st.error(job["error"])
                break
            if job["status"] == "completed":
                result = job["result"]
                if job.get("mode") == "recording":
                    open_uploaded_session(player, result["session_id"], result["video_id"])
                    return
                if result["shots_analysed"]:
                    st.session_state.clip_results = (player, result)
                    first_clip = next(shot["video_id"] for shot in result["shots"] if shot["status"] == "success")
                    open_uploaded_session(player, result["session_id"], first_clip)
                st.error("No shot clips could be analyzed.")
                st.dataframe(result["shots"], hide_index=True)
                break
            sleep(2)
    except requests.RequestException as error:
        show_request_error(error)
        if error.response is None or error.response.status_code != 404:
            st.button("Retry progress")
            return
    finally:
        progress.empty()
    st.query_params.pop("job", None)
    st.button("Upload another video")


def sessions_page(sessions):
    st.title("Practice sessions")
    st.button("Upload video", type="primary", icon=":material/upload:", on_click=go, args=("upload",))
    if sessions:
        session_cards(sessions, "all")
    else:
        st.info("You have no saved practice sessions yet.")


def requested_session(sessions):
    value = st.query_params.get("session")
    return next((item for item in sessions if str(item["session_id"]) == value), None)


def change_recording(session_id, key):
    go("session", session_id, st.session_state[key])


def session_page(player, sessions):
    st.button("Back to sessions", type="tertiary", icon=":material/arrow_back:", on_click=go, args=("sessions",))
    session = requested_session(sessions)
    if not session:
        st.warning("This practice session is unavailable for the current player.")
        return
    session_id = session["session_id"]
    st.title(session_name(session))
    st.caption(date_label(session))
    clip_results = st.session_state.get("clip_results")
    if clip_results and clip_results[0] == player and clip_results[1]["session_id"] == session_id:
        result = clip_results[1]
        st.caption(f"{result['shots_analysed']} of {result['shots_found']} shot clips analyzed.")
        with st.expander("Practice video processing results"):
            st.dataframe(result["shots"], hide_index=True)
    recordings = {item["video_id"]: item for item in fetch_recordings(player) if item["session_id"] == session_id}
    if not recordings:
        st.info("There are no recordings available for this session.")
        st.button("Discuss with AI coach", type="primary", icon=":material/chat_bubble:",
                  on_click=go, args=("coach", session_id))
        return

    requested = st.query_params.get("recording")
    if requested is not None and requested not in recordings:
        st.warning("This recording is unavailable in the selected session.")
    video_id = requested if requested in recordings else next(iter(recordings))
    if len(recordings) > 1:
        key = f"detail_recording_{player}_{session_id}_{video_id}"
        st.selectbox("Recording", list(recordings), index=list(recordings).index(video_id),
                     format_func=lambda value: recording_label(recordings[value]), key=key,
                     on_change=change_recording, args=(session_id, key))
    if st.session_state.get("upload_complete") == (player, session_id, video_id):
        st.success("Recording analyzed and saved.")
        del st.session_state.upload_complete

    recording = fetch_recordings(player, video_id)
    st.button("Discuss with AI coach", type="primary", icon=":material/chat_bubble:",
              on_click=go, args=("coach", session_id, video_id))
    video_url = None
    if recording["video_available"]:
        video_url = f"{player_url(player)}/recordings/{video_id}/video"
        with st.container(key="primary_recording"):
            st.video(video_url)
    else:
        st.info("The original recording is unavailable. Saved analysis is shown below.")

    attempt = render_recording(recording, update_outcome, show_request_error, video_url)
    if attempt:
        render_form_analysis(attempt, video_id)


def coach_page(player, sessions):
    render_coach_page(player, sessions, requested_session(sessions))


def progress_page(sessions):
    st.title("Practice progress")
    if not sessions:
        st.info("Analyze a recording to start tracking your practice history.")
        st.button("Upload video", type="primary", icon=":material/upload:", on_click=go, args=("upload",))
        return

    st.subheader("Session history")
    st.caption("Accuracy uses known outcomes. Blank counts are unavailable. Automatic outcomes are estimates.")
    st.dataframe([
        {"Session": session_name(item), "Date": date_label(item), "Attempts": item["shot_count"],
         "Makes": item.get("made"), "Misses": item.get("missed"), "Unknown": item.get("unknown"),
         "Accuracy": accuracy_label(item)}
        for item in sessions
    ], hide_index=True, width="stretch")


def render_brand(key):
    # One brand mark for the desktop rail and the mobile header; CSS shows whichever fits the screen.
    with st.container(key=key, horizontal=True, vertical_alignment="center", gap="small"):
        st.markdown(":material/sports_basketball:", width="content")
        st.markdown("**ShotCoach**", width="content")


def render_navigation(page, connected):
    active = "sessions" if page in ("upload", "session") else page
    with st.container(key="main_navigation"):
        render_brand("navigation_brand")
        for column, (slug, (label, icon)) in zip(st.columns(4), PAGES.items()):
            with column:
                options = {"on_click": continue_coaching} if slug == "coach" else {"on_click": go, "args": (slug,)}
                st.button(label, key=f"nav_{slug}", type="primary" if active == slug else "secondary",
                          icon=icon, width="stretch", **options)
        with st.container(key="navigation_player"):
            st.caption("Current player")
            name = re.sub(r"([\\`*_{}\[\]()<>#+\-.!|:~$])", r"\\\1", st.session_state.player_name)
            st.markdown(f":material/person: **{name or 'No player selected'}**")
            status = "connected" if connected else "disconnected"
            st.caption(f":{'green' if connected else 'red'}[:material/circle:] Backend {status}")


def render_styles():
    # Match native widgets and custom surfaces to the same Streamlit theme.
    tokens = {
        "text": "textColor",
        "muted": "grayTextColor",
        "page": "backgroundColor",
        "card": "secondaryBackgroundColor",
        "line": "borderColor",
        "accent": "primaryColor",
        "selection": "orangeBackgroundColor",
        "raised": "grayBackgroundColor",
    }
    declarations = "".join(f"--sc-{name}: {st.get_option(f'theme.{option}')};"
                           for name, option in tokens.items())
    st.html(f"<style>:root {{ {declarations} }}</style>")
    st.html(Path(__file__).with_name("shotcoach.css"))


def main():
    page = st.query_params.get("page", "home")
    if page not in (*PAGES, "upload", "session"):
        page = "home"
    render_styles()
    try:
        requests.get(f"{API_URL}/api/health", timeout=3).raise_for_status()
        connected = True
    except requests.RequestException:
        connected = False
    with st.sidebar:
        st.subheader("Current player")
        st.text_input("Player name", key="player_selector", on_change=change_player)
        st.caption("Use the same name for all of your practice recordings.")
        with st.container(key="sidebar_backend_status"):
            if connected:
                st.success("Backend connected")
            else:
                st.error("Backend disconnected")

    with st.container(key=f"shotcoach_header_{page}"):
        render_brand("header_brand")
    # Fixed-position navigation renders first so it stays visible during long coaching requests.
    render_navigation(page, connected)
    player = st.session_state.player_name
    try:
        if not player:
            st.info("Enter a player name to see your sessions and start coaching.")
            return
        sessions = fetch_sessions(player)
        if page == "home":
            home_page(sessions)
        elif page == "upload":
            upload_page(player, sessions)
        elif page == "sessions":
            sessions_page(sessions)
        elif page == "session":
            session_page(player, sessions)
        elif page == "coach":
            coach_page(player, sessions)
        else:
            progress_page(sessions)
    except requests.RequestException as error:
        show_request_error(error)


main()
