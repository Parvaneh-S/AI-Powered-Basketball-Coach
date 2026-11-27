"""Render coaching responses and player-entered practice context."""

from html import escape
from urllib.parse import urlencode

import requests
import streamlit as st

PHASE_LABELS = {"preparation": "Preparation", "release": "Estimated release",
                "follow_through": "Early follow-through", "landing": "Landing",
                "knee_dip": "Deepest knee bend", "knee_max": "Straightest knee position",
                "knee_extension": "Knee extension after loading",
                "elbow_min": "Most bent elbow position", "elbow_max": "Peak elbow extension",
                "post_release_extension": "Peak early follow-through extension"}


def memory_request(api_url, player, method="GET", payload=None):
    response = requests.request(method, f"{api_url}/api/coach/memory", params={"player_name": player},
                                json=payload, timeout=10)
    response.raise_for_status()
    return response.json() if response.content else None


def render_frames(api_url, player, refs, key):
    if not refs:
        return
    groups = [refs]
    if len({ref["shot_id"] for ref in refs}) > 1:
        by_phase = {}
        for ref in refs:
            focus = (ref.get("annotation") or {}).get("focus")
            by_phase.setdefault((ref["phase"], focus), []).append(ref)
        groups = list(by_phase.values())
    multiple_videos = len({ref["video_id"] for ref in refs}) > 1
    with st.container(key=f"coach_visual_{key}"):
        for group in groups:
            for start in range(0, len(group), 2):
                row = group[start:start + 2]
                columns = st.columns(2) if len(row) == 2 else [st.container()]
                for column, ref in zip(columns, row):
                    with column:
                        render_frame(api_url, player, ref, key, multiple_videos)


@st.cache_data(ttl=600, max_entries=200, show_spinner=False)
def cached_frame(api_url, player, shot_id, reference_id):
    # Failures raise, so only successfully extracted frames are cached; every rerun redraws the chat.
    frame = requests.get(f"{api_url}/api/coach/frame", timeout=30, params={
        "player_name": player, "shot_id": shot_id, "reference_id": reference_id})
    frame.raise_for_status()
    return frame.content


def frame_image(api_url, player, shot_id, reference_id):
    """JPEG bytes of a saved annotated frame, or None when it can't be loaded."""
    try:
        return cached_frame(api_url, player, shot_id, reference_id)
    except requests.RequestException:
        return None


def render_frame(api_url, player, ref, key, multiple_videos):
    params = {"player_name": player, "shot_id": ref["shot_id"]}
    image = frame_image(api_url, player, ref["shot_id"], ref["id"])
    if image is None:
        st.caption("This frame is unavailable.")
        return
    st.image(image, width="stretch")
    phase = PHASE_LABELS.get(ref["phase"], ref["phase"])
    label = f"Attempt {ref.get('shot_number', 1)}"
    if ref.get("outcome_source") == "manual" and ref.get("outcome") in ("made", "missed"):
        label += f" · {ref['outcome']} (player label)"
    st.caption(f"{label} · {phase} · {ref['timestamp_s']:.3f} s")
    if multiple_videos:
        session = ref.get("session_id")
        st.caption(f"Session {session} · {ref['video_id']}" if session is not None else ref["video_id"])
    if annotation := ref.get("annotation"):
        marks = annotation["marks"]
        if annotation["angle_deg"] is not None:
            source = "from landmarks" if annotation.get("angle_source") == "saved_landmarks" else "saved angle"
            st.caption(f"{annotation['side'].title()} {annotation['focus']} · {annotation['angle_deg']:g}° (2D, {source})")
        if not marks:
            st.caption("Landmarks unavailable for this overlay.")
        elif "image_plane_displacement" in marks:
            origin = PHASE_LABELS.get(annotation["from_phase"], annotation["from_phase"]).lower()
            st.caption(f"Arrow shows 2D joint displacement from {origin}.")
    if st.toggle("Play from this moment", key=f"{key}_{ref['id']}"):
        url = f"{api_url}/api/coach/video?{urlencode(params)}#t={ref['timestamp_s']:.3f}"
        end = ref.get("playback_end_s")
        if end is not None and end > ref["timestamp_s"]:
            url += f",{end:.3f}"
        st.html(f'<video controls playsinline preload="metadata" src="{escape(url, quote=True)}" '
                f'aria-label="{escape(phase, quote=True)}" style="display:block;width:100%"></video>')
        st.caption(f"Frame {ref['frame']} · {ref['uncertainty']}")


def render_progress(progress):
    if not progress or progress["status"] != "available":
        return
    st.markdown("**Measured**")
    left, right = st.columns(2)
    sessions = progress.get("kind") == "sessions"
    for column, title, side in ((left, "Earlier session" if sessions else "Before the focus", "before"),
                                 (right, "Later session" if sessions else "New shots", "after")):
        sample = progress[side]
        with column:
            st.markdown(f"**{title}**")
            if session_id := progress.get(f"{side}_session_id"):
                st.caption(f"Session {session_id}")
            if "manual_made" in sample:
                st.write(f"{sample['manual_made']} makes / {sample['manual_labels']} player-confirmed outcomes")
                estimates = sample["made"] + sample["missed"] - sample["manual_labels"]
                st.caption(f"{estimates} estimated · {sample['unknown']} unknown")
            else:
                st.write(f"{sample['made']} makes / {sample['made'] + sample['missed']} labelled shots")
                st.caption(f"{sample['manual_labels']} player labels · {sample['unknown']} unknown outcomes")
            if progress["field"]:
                st.caption(f"{sample['measurement_count']} usable attempts for movement")
    assessment = progress.get("assessment") or {}
    if assessment.get("phase"):
        st.caption(f"Measured phase · {assessment['phase']}")
    if progress.get("intermediate"):
        reviewed = ", ".join(str(sample["session_id"]) for sample in progress["intermediate"])
        st.caption(f"Intervening session reviewed · {reviewed}")
    if progress["completed"] or progress.get("player_reported_effect"):
        st.markdown("**Player-reported**")
        if progress["completed"]:
            st.caption("Practice completion was reported by the player.")
        if effect := progress.get("player_reported_effect"):
            st.caption(f"Player said the practice {'helped' if effect == 'helped' else 'didn’t help'}.")


def render_response(result, player, api_url, key, practice_link=None):
    """Render one coaching reply. With `practice_link`, a recommended practice is shown as a compact
    card whose full plan lives in the Practice tab."""
    st.write(result["message"])
    observations = result.get("strengths", []) + result.get("observations", [])
    refs = {ref["id"]: ref for ref in result.get("video_references", [])}
    comparison = len({ref["shot_id"] for ref in refs.values()}) > 1
    shown = set()
    for index, observation in enumerate(observations):
        st.write(observation["text"])
        if visual_focus := observation.get("visual_focus"):
            st.write(visual_focus)
        attached = [] if comparison else [refs[ref_id] for ref_id in observation["video_reference_ids"]
                                          if ref_id in refs and ref_id not in shown]
        render_frames(api_url, player, attached, f"{key}_observation_{index}")
        shown.update(ref["id"] for ref in attached)
    render_frames(api_url, player, [ref for ref in refs.values() if ref["id"] not in shown], f"{key}_frames")
    if previous := result.get("previous_focus"):
        st.caption(f"Previous focus · {previous['title']}")
        if not result.get("authored_evidence"):
            st.write(previous["cue"])
        if instructions := previous.get("practice_instructions"):
            with st.expander("Previous exercise"):
                st.write(instructions)
                if dose := previous.get("prescribed_dose"):
                    st.caption(f"{dose['sets']} sets · {dose['repetitions']} repetitions per set")
    render_progress(result.get("progress"))
    if guidance := result.get("guidance_note"):
        st.caption(guidance)
    if explanation := result.get("explanation"):
        st.write(explanation)
    if cue := result.get("cue"):
        st.markdown(f"**{cue}**")
    if (practice := result.get("practice")) and practice_link:
        with st.container(key=f"{key}_practice_card"):
            st.caption(":material/assignment: Recommended practice")
            st.markdown(f"**{practice['title']}**")
            if dose := practice.get("dose"):
                st.caption(f"{dose['sets']} {'set' if dose['sets'] == 1 else 'sets'} × {dose['repetitions']} shots")
            if practice.get("focus") and practice["focus"] != result.get("cue"):
                st.write(practice["focus"])
            practice_link()
    elif practice:
        with st.container(border=True):
            st.markdown(f"**{practice['title']}**")
            if practice.get("reason") and practice["reason"] != result.get("explanation"):
                st.write(practice["reason"])
            if practice.get("setup"):
                st.write(practice["setup"])
            if dose := practice.get("dose"):
                st.caption(f"Prescribed practice target: {dose['sets']} set(s) of {dose['repetitions']} repetitions; allow {dose['duration_seconds']} seconds including resets.")
            if practice.get("focus") and practice["focus"] != result.get("cue"):
                st.write(practice["focus"])
            st.write(practice["instructions"])
            st.write(practice["evaluation"])
            for field, label in (("success_criteria", "Success check"), ("easier_variation", "Easier option"),
                                 ("progression", "Progress when"), ("reconsider", "Reconsider when")):
                if practice.get(field) and practice[field] != practice["evaluation"]:
                    st.write(f"{label}: {practice[field]}")
            for assumption in practice.get("assumptions", []):
                st.caption(assumption)
            if practice.get("source_info"):
                st.caption("ShotCoach practice adaptation; the exercise prescription is not professionally validated.")
    if uncertainty := result.get("uncertainty"):
        st.caption(uncertainty)
    if clarification := result.get("clarification"):
        st.write(clarification)
    if next_step := result.get("next_step"):
        st.write(next_step)
    details = [item["technical"] for item in observations if item.get("technical")]
    shown_evidence = {evidence_id for item in observations for evidence_id in item.get("evidence_ids", [])}
    for evidence_id, item in (result.get("authored_evidence") or {}).get("observations", {}).items():
        if evidence_id not in shown_evidence and item.get("technical"):
            details.append(item["technical"])
    if details:
        with st.expander("Measurements", expanded=result.get("show_details", False)):
            for detail in details:
                if "value" in detail:
                    st.write(f"{detail['name']} · {detail['value']:g} {detail['unit']}")
                    st.caption(detail["provenance"])
                elif "first" in detail:
                    st.write(f"{detail['first']:g} → {detail['second']:g} {detail['unit']}")
                elif "mean_made" in detail:
                    st.write(f"Average on makes {detail['mean_made']:g} {detail['unit']} · "
                             f"average on misses {detail['mean_missed']:g} {detail['unit']}")
                elif detail.get("outcome_source"):
                    st.caption(detail["outcome_source"])
    resource = result.get("instructional_resource")
    resources = [item for item in [resource, *result.get("additional_resources", [])] if item]
    for item in resources:
        render_resource(item)
    shown_urls = {item["url"] for item in resources}
    sources = [source for source in result.get("knowledge_references", []) if source["url"] not in shown_urls]
    if sources:
        with st.expander("Supporting coaching sources"):
            for source in sources:
                if source["url"]:
                    st.markdown(f"[{source['source']}]({source['url']})")
                else:
                    st.caption(source["source"])


def render_resource(resource):
    """A recommended video or reading: what it is, why it matters for this player, and a direct link."""
    video = resource["kind"] == "video"
    with st.container(border=True):
        media, text = st.columns([1, 2]) if resource.get("thumbnail_url") else (None, st.container())
        if media is not None:
            # Thumbnails are only present when verified on the publisher's page.
            media.image(resource["thumbnail_url"], width="stretch")
        with text:
            st.markdown(f"[**{resource['title']}**]({resource['url']})")
            attribution = " · ".join(filter(None, (resource["organization"], resource.get("creator"))))
            st.caption(f"{'Instructional video' if video else 'Reading'} · {attribution}")
            st.write(resource["watch_for"])
            if section := resource.get("section"):
                st.caption(section)
        if relevance := resource.get("relevance"):
            st.markdown(f"**What to watch for:** {relevance}")
        if video and resource.get("embed_url"):
            st.video(resource["embed_url"])
        st.link_button("Watch video" if video else "Read article", resource["url"])
        if exercise := resource.get("exercise"):
            st.caption(exercise)


def render_memory(api_url, player, on_error):
    try:
        memory = memory_request(api_url, player)
    except requests.RequestException as error:
        on_error(error)
        return

    if focus := memory.get("focus"):
        with st.expander("My practice plan"):
            st.markdown(f"**Current focus · {focus['title']}**")
            st.write(focus["cue"])
            st.caption(focus["exercise"])
            render_progress(memory.get("progress"))
            reports = {"completed": "I completed the drill", "difficulty": "I found it difficult",
                       "helped": "It helped", "did_not_help": "It didn’t help"}
            with st.form(f"coach_feedback_{focus['id']}", clear_on_submit=True):
                kind = st.selectbox("Practice update", reports, format_func=reports.get)
                report = st.text_area("What happened?", max_chars=800)
                if st.form_submit_button("Save practice update"):
                    try:
                        memory_request(api_url, player, "PATCH", {
                            "focus_id": focus["id"], "report_kind": kind, "report": report,
                        })
                        st.rerun()
                    except requests.RequestException as error:
                        on_error(error)
            for report in [item for item in memory["reports"] if item["focus_id"] == focus["id"]][-3:]:
                st.caption(reports[report["kind"]] + (f" · {report['text']}" if report["text"] else ""))

    if any(memory.get(field) for field in ("goal", "experience", "preferences", "recommendations", "reports")):
        with st.sidebar.expander("Coaching history"):
            confirm = st.checkbox("Clear saved coaching for this player", key=f"confirm_reset_{player}")
            if st.button("Reset saved coaching", disabled=not confirm, key=f"reset_coaching_{player}"):
                try:
                    memory_request(api_url, player, "DELETE")
                    st.session_state.messages = []
                    st.rerun()
                except requests.RequestException as error:
                    on_error(error)
