
from pathlib import Path

import requests
import streamlit as st


API_URL = "http://127.0.0.1:8000"

st.set_page_config(
    page_title="AI Basketball ShotCoach",
    page_icon="🏀",
    layout="wide",
)


# -------------------------------------------------------
# Session state
# -------------------------------------------------------

if "analysis" not in st.session_state:
    st.session_state.analysis = None

if "video_id" not in st.session_state:
    st.session_state.video_id = None

if "player_name" not in st.session_state:
    st.session_state.player_name = "TestPlayer"

if "messages" not in st.session_state:
    st.session_state.messages = []


# -------------------------------------------------------
# API helpers
# -------------------------------------------------------

def fetch_analysis(video_id):
    response = requests.get(
        f"{API_URL}/api/shots/{video_id}",
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def upload_video(file, player_name, shooting_arm):
    response = requests.post(
        f"{API_URL}/api/shots/upload",
        files={
            "file": (
                file.name,
                file.getvalue(),
                "video/mp4",
            )
        },
        data={
            "player_name": player_name,
            "shooting_arm": shooting_arm,
        },
        timeout=900,
    )
    response.raise_for_status()
    return response.json()


def ask_coach(player_name, question):
    response = requests.post(
        f"{API_URL}/api/coach/ask",
        json={
            "player_name": player_name,
            "question": question,
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()


def show_request_error(error):
    if isinstance(error, requests.exceptions.HTTPError):
        response = error.response
        detail = response.text if response is not None else str(error)

        if response is not None:
            try:
                detail = response.json().get("detail", detail)
            except ValueError:
                pass

        st.error(f"API error: {detail}")

    elif isinstance(error, requests.exceptions.Timeout):
        st.error(
            "The request timed out. Check the FastAPI "
            "terminal to determine whether processing completed."
        )

    else:
        st.error(
            "Cannot communicate with FastAPI. "
            "Make sure the backend server is running."
        )


def set_current_shot(video_id, analysis, player_name):
    st.session_state.video_id = video_id
    st.session_state.analysis = analysis
    st.session_state.player_name = player_name
    st.session_state.messages = []


# -------------------------------------------------------
# Sidebar
# -------------------------------------------------------

with st.sidebar:
    st.title("🏀 ShotCoach")
    st.caption("Single-agent AI basketball coach")

    st.divider()

    st.subheader("Current player")
    player_name = st.text_input(
        "Player name",
        value=st.session_state.player_name,
    )

    st.caption("Use the same name for all of a player's shots.")

    st.divider()

    try:
        health = requests.get(
            f"{API_URL}/api/health",
            timeout=3,
        )
        health.raise_for_status()
        st.success("Backend connected")
    except requests.exceptions.RequestException:
        st.error("Backend disconnected")

    if st.session_state.video_id:
        st.caption("Selected video ID")
        st.code(st.session_state.video_id)

    st.divider()
    st.caption("Experimental basketball analysis prototype")


# -------------------------------------------------------
# Page header
# -------------------------------------------------------

st.title("🏀 AI Basketball ShotCoach")

st.write(
    "Upload a side-view free-throw video, "
    "analyze your shooting mechanics, and "
    "receive personalized AI coaching."
)

upload_tab, coach_tab = st.tabs([
    "📹 Upload & Analysis",
    "🤖 AI Coach",
])


# -------------------------------------------------------
# Tab 1: Video upload
# -------------------------------------------------------

with upload_tab:

    st.header("Analyze a free throw")

    with st.form("upload_form"):

        uploaded_file = st.file_uploader(
            "Choose an MP4 video",
            type=["mp4"],
        )

        shooting_arm = st.selectbox(
            "Shooting arm",
            ["right", "left"],
        )

        submit_upload = st.form_submit_button(
            "Analyze Video",
            type="primary",
        )

    if submit_upload:

        if not player_name.strip():
            st.warning("Please enter a player name.")

        elif uploaded_file is None:
            st.warning("Please select an MP4 video.")

        elif uploaded_file.size > 100 * 1024 * 1024:
            st.error("The maximum upload size is 100 MB.")

        else:

            with st.spinner(
                "Processing video. This includes pose "
                "estimation, ball tracking, hoop detection, "
                "and biomechanical analysis..."
            ):
                try:
                    result = upload_video(
                        uploaded_file,
                        player_name.strip(),
                        shooting_arm,
                    )

                    video_id = result["video_id"]

                    analysis = fetch_analysis(video_id)

                    set_current_shot(
                        video_id,
                        analysis,
                        player_name.strip(),
                    )

                    st.success(
                        "Video processed and saved successfully!"
                    )

                except (
                    requests.exceptions.RequestException,
                    KeyError,
                ) as error:
                    if isinstance(
                        error,
                        requests.exceptions.RequestException,
                    ):
                        show_request_error(error)
                    else:
                        st.error(
                            f"Unexpected API response: {error}"
                        )

    st.divider()

    st.subheader("Open an existing analysis")

    with st.form("load_form"):
        existing_video_id = st.text_input(
            "Video ID",
            placeholder="shot_b8a4046d9f91",
        )

        load_clicked = st.form_submit_button(
            "Load Shot"
        )

    if load_clicked:

        if not existing_video_id.strip():
            st.warning("Enter a video ID first.")

        else:
            try:
                analysis = fetch_analysis(
                    existing_video_id.strip()
                )

                set_current_shot(
                    existing_video_id.strip(),
                    analysis,
                    player_name.strip(),
                )

                st.success("Shot analysis loaded.")

            except requests.exceptions.RequestException as error:
                show_request_error(error)

    # ---------------------------------------------------
    # Display shot analysis
    # ---------------------------------------------------

    if st.session_state.analysis:

        analysis = st.session_state.analysis
        biomechanics = analysis.get("biomechanics", {})
        events = analysis.get("shot_events", {})
        outcome = analysis.get("shot_outcome", {})
        tracking = analysis.get("ball_tracking", {})

        st.divider()
        st.header("Shot Analysis")

        st.caption(
            f"Video ID: {st.session_state.video_id}"
        )

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Minimum knee angle",
                f"{biomechanics.get('min_knee_angle', 'N/A')}°",
            )

        with col2:
            st.metric(
                "Release elbow angle",
                f"{biomechanics.get('release_elbow_angle', 'N/A')}°",
            )

        with col3:
            st.metric(
                "Start-to-release duration",
                f"{biomechanics.get('shooting_motion_ms', 'N/A')} ms",
            )

        col4, col5, col6 = st.columns(3)

        with col4:
            st.metric(
                "Knee angle range",
                f"{biomechanics.get('knee_angle_range', 'N/A')}°",
            )

        with col5:
            st.metric(
                "Elbow angle range",
                f"{biomechanics.get('elbow_angle_range', 'N/A')}°",
            )

        with col6:
            st.metric(
                "Elbow extension after release",
                f"{biomechanics.get('elbow_extension_after_release', 'N/A')}°",
            )

        st.subheader("Outcome and quality")

        col7, col8, col9 = st.columns(3)

        with col7:
            st.metric(
                "Predicted outcome",
                str(outcome.get("prediction", "unknown")).title(),
            )

        with col8:
            st.metric(
                "Measurement quality",
                str(
                    biomechanics.get("measurement_quality", "unknown")
                ).title(),
            )

        with col9:
            st.metric(
                "Tracked ball frames",
                tracking.get("tracked_frames", "N/A"),
            )

        st.warning(
            "Experimental analysis: measurement quality "
            "reflects tracking coverage, not verified "
            "biomechanical accuracy. An unknown outcome "
            "must not be treated as a make or a miss."
        )

        with st.expander("Detailed analysis JSON"):
            st.json(analysis)

        # ------------------------------------------------
        # Visual feedback: local development only
        # ------------------------------------------------

        st.subheader("Visual feedback")

        # The backend and Streamlit currently run on
        # the same local computer, so these paths work.
        output_dir = (
            Path(__file__).resolve().parents[1]
            / "outputs"
            / st.session_state.video_id
        )

        video_left, video_right = st.columns(2)

        with video_left:
            st.write("**Pose and joint angles**")

            pose_video = output_dir / "annotated_angles.mp4"

            if pose_video.is_file():
                st.video(str(pose_video))
            else:
                st.info("Annotated pose video unavailable.")

        with video_right:
            st.write("**Basketball tracking**")

            ball_video = output_dir / "ball_tracking.mp4"

            if ball_video.is_file():
                st.video(str(ball_video))
            else:
                st.info("Ball-tracking video unavailable.")

        hoop_image = output_dir / "hoop_detection.jpg"

        if hoop_image.is_file():
            with st.expander("Hoop detection image"):
                st.image(str(hoop_image))

        st.info(
            "Open the AI Coach tab to ask questions "
            "about the selected shot."
        )


# -------------------------------------------------------
# Tab 2: AI coaching
# -------------------------------------------------------

with coach_tab:

    st.header("Ask your AI Basketball Coach")

    if not st.session_state.video_id:

        st.info(
            "First upload a video or load an existing "
            "shot from the Upload & Analysis tab."
        )

    else:

        video_id = st.session_state.video_id

        st.caption(f"Current shot: {video_id}")

        st.write(
            "Ask about your measurements, shooting form, "
            "previous shots, or coaching recommendations."
        )

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        with st.form("coach_form", clear_on_submit=True):

            question = st.text_area(
                "Your question",
                placeholder=(
                    "How can I improve my knee bend "
                    "and elbow extension?"
                ),
                height=100,
            )

            ask_clicked = st.form_submit_button(
                "Ask Coach",
                type="primary",
            )

        if ask_clicked:

            if not question.strip():
                st.warning("Please enter a question.")

            elif not player_name.strip():
                st.warning("Please enter a player name.")

            else:

                # Give the agent the selected video's ID.
                contextual_question = (
                    f"Current selected video ID: {video_id}. "
                    f"User question: {question.strip()}"
                )

                st.session_state.messages.append({
                    "role": "user",
                    "content": question.strip(),
                })

                with st.chat_message("user"):
                    st.markdown(question.strip())

                with st.chat_message("assistant"):

                    with st.spinner(
                        "The AI coach is analyzing your question..."
                    ):

                        try:
                            result = ask_coach(
                                player_name.strip(),
                                contextual_question,
                            )

                            answer = result.get(
                                "answer",
                                "No coaching feedback returned.",
                            )

                            if not isinstance(answer, str):
                                answer = str(answer)

                            st.markdown(answer)

                            st.session_state.messages.append({
                                "role": "assistant",
                                "content": answer,
                            })

                        except requests.exceptions.RequestException as error:
                            show_request_error(error)

        if st.button("Clear chat history"):
            st.session_state.messages = []
            st.rerun()
