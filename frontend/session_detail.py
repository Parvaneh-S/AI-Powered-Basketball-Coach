from pathlib import Path

import requests
import streamlit as st


ROOT = Path(__file__).resolve().parents[1]

FORM_MEASUREMENTS = (
    ("Minimum knee angle", "min_knee_angle", "°"),
    ("Release elbow angle", "release_elbow_angle", "°"),
    ("Start-to-release duration", "shooting_motion_ms", " ms"),
    ("Knee angle range", "knee_angle_range", "°"),
    ("Elbow angle range", "elbow_angle_range", "°"),
    ("Elbow extension after release", "elbow_extension_after_release", "°"),
)


def render_form_analysis(analysis, video_id):
    biomechanics = analysis.get("biomechanics", {})
    outcome = analysis.get("shot_outcome", {})
    tracking = analysis.get("ball_tracking", {})

    st.divider()
    st.subheader("Form and tracking")

    for row in (FORM_MEASUREMENTS[:3], FORM_MEASUREMENTS[3:]):
        for column, (label, field, unit) in zip(st.columns(3), row):
            value = biomechanics.get(field)
            column.metric(label, f"{value}{unit}" if value is not None else "Unavailable")

    st.subheader("Outcome and quality")

    col7, col8, col9 = st.columns(3)

    final_outcome = outcome.get(
        "final_outcome",
        outcome.get("prediction", "unknown"),
    )
    outcome_source = outcome.get("outcome_source", "auto")

    with col7:
        st.metric(
            "Outcome",
            str(final_outcome).title(),
            help=(
                "Set manually by the player"
                if outcome_source == "manual"
                else "Automatic detection (experimental)"
            ),
        )
        st.caption(
            "Source: manual label"
            if outcome_source == "manual"
            else "Source: automatic detection"
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

    st.subheader("Visual feedback")

    # The existing overlays are local artifacts shared by the two services.
    output_dir = ROOT / "outputs" / video_id

    video_left, video_right = st.columns(2)

    with video_left:
        st.write("**Pose and joint angles**")

        pose_video = output_dir / "annotated_angles_web.mp4"

        if pose_video.is_file():
            st.video(str(pose_video))
        else:
            st.info("Annotated pose video unavailable.")

    with video_right:
        st.write("**Basketball tracking**")

        ball_video = output_dir / "ball_tracking_web.mp4"

        if ball_video.is_file():
            st.video(str(ball_video))
        else:
            st.info("Ball-tracking video unavailable.")

    hoop_image = output_dir / "hoop_detection.jpg"

    if hoop_image.is_file():
        with st.expander("Hoop detection image"):
            st.image(str(hoop_image))


def render_recording(recording, label_attempt, on_error, video_url):
    summary = recording["summary"]
    attempts = recording["attempts"]
    st.subheader("Session summary")
    attempts_col, accuracy_col, coverage_col = st.columns(3)
    attempts_col.metric("Detected attempts", summary["attempts"])
    accuracy = summary["accuracy_pct"]
    accuracy_col.metric("Accuracy on known outcomes", f"{accuracy:g}%" if accuracy is not None else "Unavailable")
    coverage = summary["outcome_coverage_pct"]
    coverage_col.metric("Outcome coverage", f"{coverage:g}%" if coverage is not None else "Unavailable")
    with st.container(horizontal=True, key="outcome_legend"):
        st.badge(f"{summary['made']} made", color="green", icon=":material/check:")
        st.badge(f"{summary['missed']} missed", color="red", icon=":material/close:")
        st.badge(f"{summary['unknown']} unknown", color="gray")
    st.caption(f"{summary['reliable_form_attempts']} with usable form measurements")
    processing = recording["processing"]
    if processing.get("hoop_available") is False:
        st.caption("Hoop tracking was unavailable for this recording. Automatic outcomes are unknown.")
    if count := processing.get("review_candidate_count"):
        st.caption(f"{count} additional motion cues need review. They are excluded from the attempt count.")
    if not attempts:
        st.info("No shooting attempts could be verified in this recording.")
        return
    with st.expander("Attempt details", expanded=True):
        choices = {attempt["shot_id"]: attempt for attempt in attempts}
        shot_id = st.selectbox("Attempt", choices, key=f"attempt_{recording['video_id']}", format_func=lambda key: (
            f"Shot {choices[key]['shot_number']} · {choices[key]['shot_outcome']['final_outcome']}"
        ))
        attempt = choices[shot_id]
        events = attempt.get("shot_events") or {}
        timeline = [
            f"{label} {events[field] / 1000:.2f} s"
            for field, label in (
                ("start_time_ms", "Start"),
                ("release_time_ms", "Estimated release"),
                ("end_time_ms", "Early follow-through"),
            )
            if events.get(field) is not None
        ]
        if timeline:
            st.caption(" · ".join(timeline))
        if video_url and events.get("start_time_ms") is not None and st.toggle(
            "Play from this attempt", key=f"play_attempt_{shot_id}"
        ):
            st.video(video_url, start_time=int(events["start_time_ms"] / 1000))
        with st.form(f"label_attempt_{shot_id}"):
            outcomes = {"made": "Made", "missed": "Missed", "auto": "Detector estimate"}
            outcome = st.selectbox("Outcome label", outcomes, format_func=outcomes.get)
            if st.form_submit_button("Save outcome"):
                try:
                    label_attempt(shot_id, outcome)
                    st.rerun()
                except requests.RequestException as error:
                    on_error(error)
    return attempt
