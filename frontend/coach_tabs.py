"""AI Coach page: Coach, Practice and Progress tabs built on the existing coaching APIs.

Everything shown here comes from saved recordings, the coaching memory (`/api/coach/memory`) or
responses from `/api/coach/ask`. Nothing is generated in the frontend: no plans, trends or stats.
"""

from datetime import datetime
from pathlib import Path

import requests
import streamlit as st

from frontend.coaching import (PHASE_LABELS, frame_image, memory_request, render_progress, render_resource,
                               render_response)
from frontend.service import (API_URL, ask_coach, error_text, fetch_recordings, fetch_session_summary,
                              show_request_error)

TABS = {"coach": "Coach", "practice": "Practice", "progress": "Progress"}
SUGGESTIONS = (
    ("Analyze my shooting form", ":material/accessibility_new:"),
    ("Why am I missing shots?", ":material/sports_basketball:"),
    ("How am I improving?", ":material/trending_up:"),
    ("What should I practice?", ":material/assignment:"),
)
REPORTS = {"completed": "Completed the practice", "difficulty": "Found it too difficult",
           "helped": "It helped", "did_not_help": "It didn’t help"}
FEEDBACK = {"difficulty": "Too difficult", "helped": "It helped", "did_not_help": "It didn’t help"}
# Technique measures shown on Progress. Direction is never judged: higher is not assumed to be better.
TECHNIQUE = (("min_knee_angle", "Knee bend (smallest knee angle)", "°"),
             ("max_elbow_angle", "Peak arm extension (largest elbow angle)", "°"),
             ("release_elbow_angle", "Release elbow angle", "°"))
MIN_COMPARABLE = 3  # reliable attempts per session before a session joins a trend or chart
COMPARE_PHASES = {"release": "Estimated release", "knee_dip": "Deepest knee bend"}


# ---------------------------------------------------------------- navigation and state

def set_tab(tab, question=None, pair=None):
    st.session_state.coach_tab_select = tab
    st.query_params["tab"] = tab
    if question:
        st.session_state.pending_question = (question, pair)


def tab_changed():
    tab = st.session_state.coach_tab_select or st.query_params.get("tab", "coach")
    st.session_state.coach_tab_select = tab
    st.query_params["tab"] = tab


def queue_question(question, pair=None):
    st.session_state.pending_question = (question, pair)


def short_name(recording):
    name = recording.get("name") or recording["video_id"]
    return Path(name).stem if "." in name else name


def attempt_count(count):
    return f"{count} detected {'attempt' if count == 1 else 'attempts'}"


def outcome_of(attempt):
    outcome = attempt.get("shot_outcome") or {}
    return outcome.get("final_outcome") or outcome.get("prediction") or "unknown"


def attempt_label(attempt):
    label = f"Attempt {attempt['shot_number']} · {outcome_of(attempt)}"
    if (attempt.get("shot_outcome") or {}).get("outcome_source") == "manual":
        label += " (your label)"
    return label


def date_text(value):
    try:
        return datetime.fromisoformat(value).astimezone().strftime("%b %d, %Y")
    except (TypeError, ValueError):
        return "Date unavailable"


def fetch_memory(player):
    try:
        return memory_request(API_URL, player), None
    except requests.RequestException as error:
        return None, error


# ---------------------------------------------------------------- page

def render_coach_page(player, sessions, requested_session):
    st.session_state.setdefault("coach_tab_select", st.query_params.get("tab", "coach"))
    if st.session_state.coach_tab_select not in TABS:
        st.session_state.coach_tab_select = "coach"
    with st.container(key="coach_heading"):
        st.title("AI Coach", anchor=False)
        st.segmented_control("Coach view", list(TABS), format_func=TABS.get, key="coach_tab_select", required=True,
                             on_change=tab_changed, label_visibility="collapsed")
    tab = st.session_state.coach_tab_select or "coach"
    try:
        recordings = fetch_recordings(player)
    except requests.RequestException as error:
        show_request_error(error)
        recordings = []
    if tab == "practice":
        render_practice_tab(player)
    elif tab == "progress":
        render_progress_tab(player, sessions, recordings)
    else:
        render_coach_tab(player, sessions, recordings, requested_session)
    render_reset(player)


# ---------------------------------------------------------------- Coach tab

def change_context(key, recordings):
    video_id = st.session_state[key]
    params = {"page": "coach", "tab": "coach"}
    if video_id:
        params.update(session=str(recordings[video_id]["session_id"]), recording=video_id)
    st.query_params.from_dict(params)


def change_attempt(key):
    shot_id = st.session_state[key]
    if shot_id:
        st.query_params["attempt"] = shot_id
    else:
        st.query_params.pop("attempt", None)


def render_context(player, session, recordings, sessions):
    """Compact selector naming the recording and attempt the coach is discussing."""
    by_id = {item["video_id"]: item for item in recordings}
    names = {item["session_id"]: session_title(item) for item in sessions}
    video_id = st.query_params.get("recording")
    recording = by_id.get(video_id) if video_id else None
    if recording and session and recording["session_id"] != session["session_id"]:
        recording = None
    detail, attempt = None, None
    if recording:
        try:
            detail = fetch_recordings(player, recording["video_id"])
        except requests.RequestException:
            detail = None
        attempts = {item["shot_id"]: item for item in (detail or {}).get("attempts", [])}
        attempt = attempts.get(st.query_params.get("attempt"))
        count = recording["shot_count"]
        scope = attempt_label(attempt) if attempt else ("Entire session" if count > 1 else "Single shot")
        title, summary = short_name(recording), f"{attempt_count(count)} · {scope}"
    elif session:
        title = session.get("name") or f"Practice session {session['session_id']}"
        summary = f"{attempt_count(session['shot_count'])} · Whole session"
    else:
        attempts = {}
        title = "No recording selected"
        summary = "Coaching uses all of your saved practice" if recordings else "No recordings yet"
    with st.container(key="coach_context"):
        with st.popover(f"**{title}**  \n{summary}", icon=":material/videocam:", width="stretch"):
            key = f"coach_recording_{player}_{recording['video_id'] if recording else ''}"
            options = ["", *by_id]
            st.selectbox("Recording", options, index=options.index(recording["video_id"]) if recording else 0,
                         key=key, on_change=change_context, args=(key, by_id),
                         format_func=lambda value: (f"{short_name(by_id[value])} · {names.get(by_id[value]['session_id'], 'Session')}"
                                                    f" · {attempt_count(by_id[value]['shot_count'])}")
                         if value else "No recording · all practice")
            if recording and len(attempts) > 1:
                attempt_key = f"coach_attempt_{player}_{recording['video_id']}_{attempt['shot_id'] if attempt else ''}"
                options = ["", *attempts]
                st.selectbox("Attempt", options, index=options.index(attempt["shot_id"]) if attempt else 0,
                             key=attempt_key, on_change=change_attempt, args=(attempt_key,),
                             format_func=lambda value: attempt_label(attempts[value]) if value else "Entire session")
            if recording and detail is None:
                st.caption("Attempt details are unavailable right now.")
    label = title if not attempt else f"{title} · Attempt {attempt['shot_number']}"
    return recording, attempt, label


def render_coach_tab(player, sessions, recordings, session):
    if not session and "session" in st.query_params:
        st.warning("This practice session is unavailable for the current player.")
    recording, attempt, context_label = render_context(player, session, recordings, sessions)
    session_id = recording["session_id"] if recording else (session["session_id"] if session else None)
    selected = attempt["shot_id"] if attempt else (recording["video_id"] if recording else None)
    st.session_state.coach_session = session_id
    st.session_state.coach_recording = recording["video_id"] if recording else None

    # The input is pinned to the bottom wherever it is called; calling it first keeps it usable
    # while earlier replies (and their frames) redraw.
    typed = st.chat_input("Ask your coach anything…", max_chars=2000)
    messages = st.session_state.messages
    if not messages and not st.session_state.get("pending_question") and not typed:
        with st.container(key="coach_empty"):
            st.markdown("### Let’s work on your shot.")
            st.caption("Ask about your recordings, your misses, your progress or what to practise next."
                       if recordings else "Upload a recording for feedback on your own shots. You can still ask "
                                          "general shooting questions.")
            with st.container(key="coach_suggestions"):
                for row in (SUGGESTIONS[:2], SUGGESTIONS[2:]):
                    for column, (text, icon) in zip(st.columns(2), row):
                        column.button(text, icon=icon, width="stretch", key=f"suggest_{text}",
                                      on_click=queue_question, args=(text,))

    for index, message in enumerate(messages):
        render_message(message, player, index)

    pending = st.session_state.pop("pending_question", None)
    question, pair = (typed, None) if typed and typed.strip() else (pending or (None, None))
    if question and question.strip():
        ask(player, question.strip(), pair, selected, session_id, context_label)
    elif messages:
        st.button("Clear this conversation", type="tertiary", icon=":material/delete_sweep:",
                  key="clear_conversation", on_click=clear_conversation)


def clear_conversation():
    st.session_state.messages = []


def render_message(message, player, index):
    role = message["role"]
    if role == "user":
        with st.chat_message("user", avatar=":material/person:", width="content"):
            st.write(message["content"])
            if context := message.get("context"):
                st.caption(context)
        return
    with st.chat_message("assistant", avatar=":material/sports_basketball:", width="stretch"):
        st.caption("ShotCoach")
        render_response(message["coaching"], player, API_URL, f"coach_message_{index}",
                        practice_link=lambda: st.button("View in Practice", icon=":material/assignment:",
                                                        key=f"view_practice_{index}", on_click=set_tab,
                                                        args=("practice",)))


def ask(player, question, pair, selected, session_id, context_label):
    messages = st.session_state.messages
    prior = [{"role": item["role"], "content": item["content"][:4000]} for item in messages[-10:]]
    with st.chat_message("user", avatar=":material/person:", width="content"):
        st.write(question)
        st.caption(context_label)
    with st.chat_message("assistant", avatar=":material/sports_basketball:", width="stretch"):
        st.caption("ShotCoach")
        try:
            with st.spinner("Your coach is reviewing your shots…", show_time=True):
                result = ask_coach(player, question, selected, prior, pair, session_id)
        except requests.RequestException as error:
            st.error(f"Your coach couldn’t answer just now. {error_text(error)}", icon=":material/error:")
            st.button("Try again", icon=":material/refresh:", key="retry_question",
                      on_click=queue_question, args=(question, pair))
            return
    messages.extend([
        {"role": "user", "content": question, "context": context_label},
        {"role": "assistant", "content": result["answer"], "coaching": result["coaching"]},
    ])
    st.session_state.messages = messages[-24:]
    st.rerun()


# ---------------------------------------------------------------- Practice tab

def practice_details(focus):
    """The coach's full drill text for this plan, if it was given in this conversation.

    The memory API stores the focus, cue, exercise name and dose but not the drill instructions,
    success criteria or resources, so those come from the coaching response that recommended it.
    """
    for message in reversed(st.session_state.messages):
        coaching = message.get("coaching") or {}
        practice = coaching.get("practice")
        if practice and ((focus.get("drill_id") and practice.get("drill_id") == focus["drill_id"])
                         or practice.get("title") == focus.get("exercise")):
            return practice, coaching
    return None, None


def save_report(player, focus_id, kind, text=""):
    try:
        memory_request(API_URL, player, "PATCH", {"focus_id": focus_id, "report_kind": kind, "report": text})
    except requests.RequestException as error:
        st.session_state.practice_error = error_text(error)
    else:
        st.session_state.practice_saved = "Saved. Your coach will see this next time you ask."
        st.session_state[f"practice_note_{focus_id}"] = ""


def save_feedback(player, focus_id):
    kind = st.session_state.get(f"practice_feedback_{focus_id}")
    text = st.session_state.get(f"practice_note_{focus_id}", "")
    if not kind:
        st.session_state.practice_error = "Choose how the practice went before saving."
        return
    save_report(player, focus_id, kind, text)


def why_recommended(focus, practice):
    if practice and practice.get("reason"):
        return practice["reason"]
    parts = []
    if focus.get("verified_personal_correction") or focus.get("guidance_basis") == "personal_pattern":
        parts.append("Based on a pattern measured in your own recorded shots.")
    else:
        parts.append("Based on general shooting guidance, not a measured difference in your shots.")
    if shots := len(focus.get("baseline_shot_ids") or []):
        parts.append(f"Your coach reviewed {shots} recorded {'shot' if shots == 1 else 'shots'} when choosing it.")
    if focus.get("decision") == "modify":
        parts.append("It adjusts your previous practice focus.")
    return " ".join(parts)


def render_practice_tab(player):
    memory, error = fetch_memory(player)
    if error:
        st.error(f"Your practice plan couldn’t be loaded. {error_text(error)}", icon=":material/error:")
        st.button("Retry", icon=":material/refresh:", key="practice_retry")
        return
    focus = memory.get("focus")
    reports = memory.get("reports", [])
    if message := st.session_state.pop("practice_saved", None):
        st.success(message, icon=":material/check_circle:")
    if message := st.session_state.pop("practice_error", None):
        st.error(message, icon=":material/error:")

    if not focus:
        with st.container(key="practice_empty"):
            st.markdown("### No practice plan yet")
            st.caption("Your coach saves a plan when you ask what to practise. It will appear here with its "
                       "cue, sets and how to tell it’s working.")
            left, right = st.columns(2)
            left.button("Ask what to practise", type="primary", icon=":material/chat_bubble:", width="stretch",
                        key="practice_ask", on_click=set_tab, args=("coach", "What should I practice?"))
            right.button("Back to Coach", icon=":material/arrow_back:", width="stretch", key="practice_back",
                         on_click=set_tab, args=("coach",))
    else:
        render_current_plan(player, focus, reports, memory.get("progress"))
    render_practice_history(memory, focus)


def render_current_plan(player, focus, reports, progress):
    practice, coaching = practice_details(focus)
    own = [item for item in reports if item["focus_id"] == focus["id"]]
    completed = next((item for item in own if item["kind"] == "completed"), None)
    with st.container(key="practice_plan"):
        head, badge = st.columns([3, 1], vertical_alignment="center")
        head.markdown("#### Your practice plan")
        badge.markdown(":green-badge[Completed]" if completed else ":orange-badge[Active]", width="stretch",
                       text_alignment="right")
        st.caption(f"Current coaching focus · recommended {date_text(focus.get('recorded_at'))}")
        st.markdown(f"**{focus['title']}**")
        st.write(why_recommended(focus, practice))
        st.divider()
        st.markdown(f"**{focus['exercise']}**")
        if dose := (practice or {}).get("dose") or focus.get("prescribed_dose"):
            sets, shots = st.columns(2)
            sets.metric("Sets", dose["sets"])
            shots.metric("Shots per set", dose["repetitions"])
            st.caption(f"Allow about {dose['duration_seconds']} seconds including resets.")
        if practice:
            if practice.get("setup"):
                st.write(practice["setup"])
            st.write(practice["instructions"])
        with st.container(key="practice_cue"):
            st.caption("Coaching cue")
            st.write(focus["cue"])
        criteria = (practice or {}).get("success_criteria") or (practice or {}).get("evaluation")
        st.markdown("**Success criteria**")
        st.write(criteria or "Ask your coach how to tell this practice is working. The saved plan keeps the focus, "
                             "cue and sets; success criteria come with the coach’s recommendation in the chat.")
        for field, label in (("easier_variation", "Easier option"), ("progression", "Progress when")):
            if (practice or {}).get(field):
                st.caption(f"{label}: {practice[field]}")
        if completed:
            st.caption(f":material/check_circle: You marked this complete on {date_text(completed.get('recorded_at'))}.")
        else:
            st.button("Mark practice complete", type="primary", icon=":material/check:", width="stretch",
                      key=f"practice_complete_{focus['id']}", on_click=save_report,
                      args=(player, focus["id"], "completed"))

    resources = [item for item in [(coaching or {}).get("instructional_resource"),
                                   *(coaching or {}).get("additional_resources", [])] if item]
    if resources:
        st.markdown("**Related resources**")
        for item in resources:
            render_resource(item)

    st.markdown("#### How did your practice go?")
    st.segmented_control("How did your practice go?", list(FEEDBACK), format_func=FEEDBACK.get,
                         key=f"practice_feedback_{focus['id']}", label_visibility="collapsed", width="stretch")
    st.text_area("Tell your coach what worked or didn’t work", max_chars=800, key=f"practice_note_{focus['id']}",
                 placeholder="For example: my elbow drifted out when I got tired.")
    save, discuss = st.columns(2)
    save.button("Save feedback", icon=":material/save:", width="stretch", key=f"practice_save_{focus['id']}",
                on_click=save_feedback, args=(player, focus["id"]))
    discuss.button("Discuss this plan with your coach", icon=":material/chat_bubble:", width="stretch",
                   key="practice_discuss", on_click=set_tab,
                   args=("coach", f"Can we talk about my practice plan ({focus['exercise']})?"))
    feedback = [item for item in own if item["kind"] != "completed"]
    for item in feedback:
        st.caption(f"{date_text(item.get('recorded_at'))} · {REPORTS[item['kind']]}"
                   + (f" · “{item['text']}”" if item.get("text") else ""))
    if progress and progress.get("status") == "available":
        with st.expander("Measured since this focus started"):
            render_progress(progress)
            for limitation in progress.get("limitations", []):
                st.caption(limitation)


def render_practice_history(memory, focus):
    past = [item for item in memory.get("recommendations", []) if not focus or item["id"] != focus["id"]]
    if not past:
        return
    reports = memory.get("reports", [])
    with st.expander(f"Practice history · {len(past)} earlier {'plan' if len(past) == 1 else 'plans'}"):
        history = memory["recommendations"]
        for item in reversed(past):
            position = history.index(item)
            following = history[position + 1] if position + 1 < len(history) else None
            st.markdown(f"**{item['title']}** · {item['exercise']}")
            line = f"Recommended {date_text(item.get('recorded_at'))}"
            if dose := item.get("prescribed_dose"):
                line += f" · {dose['sets']} × {dose['repetitions']} shots"
            own = [report for report in reports if report["focus_id"] == item["id"]]
            line += " · Completed" if any(report["kind"] == "completed" for report in own) else " · Not marked complete"
            if following:
                line += (" · Focus changed afterwards" if following["title"] != item["title"]
                         else " · Same focus, practice adjusted afterwards")
            st.caption(line)
            for report in own:
                if report["kind"] != "completed":
                    st.caption("You said: " + REPORTS[report["kind"]]
                               + (f" · “{report['text']}”" if report.get("text") else ""))


def render_reset(player):
    with st.sidebar.expander("Coaching history"):
        confirm = st.checkbox("Clear saved coaching for this player", key=f"confirm_reset_{player}")
        if st.button("Reset saved coaching", disabled=not confirm, key=f"reset_coaching_{player}"):
            try:
                memory_request(API_URL, player, "DELETE")
                st.session_state.messages = []
                st.rerun()
            except requests.RequestException as error:
                show_request_error(error)


# ---------------------------------------------------------------- Progress tab

def session_title(session):
    return session.get("name") or f"Session {session['session_number'] if 'session_number' in session else session['session_id']}"


def render_progress_tab(player, sessions, recordings):
    analysed = [item for item in sessions if item.get("shot_count")]
    if not analysed:
        with st.container(key="progress_empty"):
            st.markdown("### No progress to show yet")
            st.caption("Upload a practice recording. Progress appears once your shots are analysed.")
            st.button("Upload video", type="primary", icon=":material/upload:", key="progress_upload",
                      on_click=lambda: st.query_params.from_dict({"page": "upload"}))
        return
    chronological = list(reversed(analysed))
    known = sum((item.get("made") or 0) + (item.get("missed") or 0) for item in analysed)
    unknown = sum(item.get("unknown") or 0 for item in analysed)
    made = sum(item.get("made") or 0 for item in analysed)
    with st.container(key="progress_overview"):
        head, badge = st.columns([3, 1], vertical_alignment="center")
        head.markdown("#### Your shooting progress")
        badge.markdown(f":gray-badge[{len(analysed)} analysed {'session' if len(analysed) == 1 else 'sessions'}]",
                       text_alignment="right", width="stretch")
        first, second, third = st.columns(3)
        first.metric("Attempts", sum(item["shot_count"] for item in analysed))
        second.metric("Confirmed", f"{known}", help="Made or missed. Unknown outcomes are not counted as misses.")
        third.metric("Unknown", unknown, help="No made or missed result could be confirmed.")
        if known:
            st.caption(f"Overall {made} made of {known} confirmed outcomes ({made / known:.0%}). "
                       "Automatic outcomes are estimates.")

    st.markdown("#### Accuracy by session")
    rows = []
    for item in chronological:
        item_known = (item.get("made") or 0) + (item.get("missed") or 0)
        rows.append({"Session": session_title(item), "Date": item.get("date") or "–", "Attempts": item["shot_count"],
                     "Made": item.get("made"), "Missed": item.get("missed"), "Unknown": item.get("unknown"),
                     "Accuracy (confirmed)": f"{item['made']}/{item_known} · {item['accuracy_pct']:g}%"
                     if item_known and item.get("accuracy_pct") is not None else "No confirmed outcomes"})
    chartable = [item for item in chronological
                 if (item.get("made") or 0) + (item.get("missed") or 0) >= MIN_COMPARABLE]
    if len(chartable) >= 2:
        st.altair_chart(accuracy_chart(chartable), width="stretch")
        st.caption(f"Only sessions with at least {MIN_COMPARABLE} confirmed outcomes are charted.")
    else:
        st.caption(f"A chart appears once two sessions each have at least {MIN_COMPARABLE} confirmed outcomes. "
                   "Single-shot sessions are listed but not trended.")
    st.dataframe(rows, hide_index=True, width="stretch")

    summaries = {}
    for item in analysed:
        try:
            summary = fetch_session_summary(player, item["session_id"])
        except requests.RequestException:
            continue
        if summary.get("status") == "available":
            summaries[item["session_id"]] = summary
    render_technique(chronological, summaries)
    memory, _ = fetch_memory(player)
    render_journey(memory)
    render_comparison(player, recordings, {item["session_id"]: item for item in analysed}, summaries)
    st.button("Discuss my progress with AI Coach", icon=":material/chat_bubble:", width="stretch",
              key="progress_discuss", on_click=set_tab, args=("coach", "How am I improving?"))


def accuracy_chart(sessions):
    import altair as alt  # bundled with Streamlit

    data = [{"Session": session_title(item), "Accuracy": item["accuracy_pct"] / 100,
             "Confirmed": (item.get("made") or 0) + (item.get("missed") or 0), "Order": index}
            for index, item in enumerate(sessions)]
    base = alt.Chart(alt.Data(values=data)).encode(
        x=alt.X("Session:N", sort=alt.SortField("Order"), title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Accuracy:Q", scale=alt.Scale(domain=[0, 1]), axis=alt.Axis(format="%", tickCount=5), title=None),
        tooltip=[alt.Tooltip("Session:N"), alt.Tooltip("Accuracy:Q", format=".0%"), alt.Tooltip("Confirmed:Q")])
    accent, text = st.get_option("theme.primaryColor"), st.get_option("theme.textColor")
    line = base.mark_line(point=alt.OverlayMarkDef(size=60, color=accent), strokeWidth=2.5, color=accent)
    labels = base.mark_text(dy=-12, fontWeight="bold", color=text).encode(text=alt.Text("Accuracy:Q", format=".0%"))
    return (line + labels).properties(height=220)


def render_technique(chronological, summaries):
    st.markdown("#### Technique across sessions")
    shown = False
    for field, label, unit in TECHNIQUE:
        points = [(item, summaries[item["session_id"]]["measurements"].get(field))
                  for item in chronological if item["session_id"] in summaries]
        points = [(item, value) for item, value in points if value and value.get("sample", 0) >= MIN_COMPARABLE]
        if not points:
            continue
        shown = True
        latest_item, latest = points[-1]
        line = f"{session_title(latest_item)}: median {latest['median']:g}{unit} over {latest['sample']} attempts"
        if latest.get("spread") is not None:
            line += f", typical variation ±{latest['spread']:g}{unit}"
        if len(points) >= 2:
            earlier_item, earlier = points[-2]
            delta = latest["median"] - earlier["median"]
            line = (f"{session_title(earlier_item)} {earlier['median']:g}{unit} → {session_title(latest_item)} "
                    f"{latest['median']:g}{unit} ({delta:+.1f}{unit}, medians of {earlier['sample']} and "
                    f"{latest['sample']} attempts)")
        st.markdown(f"**{label}**")
        st.caption(line)
    if not shown:
        st.caption(f"Technique changes need sessions with at least {MIN_COMPARABLE} reliably measured attempts.")
    elif sum(1 for item in chronological if item["session_id"] in summaries
             and summaries[item["session_id"]].get("reliable_form_attempts", 0) >= MIN_COMPARABLE) < 2:
        st.caption("Only one session has enough measured attempts, so these are a baseline, not a trend. "
                   "Angles are 2D estimates; a different value is not automatically better or worse.")
    else:
        st.caption("Angles are 2D estimates that depend on camera position. A higher or lower value is not "
                   "automatically better; compare recordings filmed from the same spot.")


def render_journey(memory):
    if not memory or not memory.get("recommendations"):
        return
    st.markdown("#### Coaching journey")
    reports = memory.get("reports", [])
    for item in memory["recommendations"][-4:]:
        own = [REPORTS[report["kind"]] for report in reports if report["focus_id"] == item["id"]]
        st.markdown(f"**{item['title']}** · {item['exercise']}")
        st.caption(f"{date_text(item.get('recorded_at'))} · You reported: {', '.join(own) if own else 'nothing yet'}")
    progress = memory.get("progress")
    if progress and progress.get("status") == "available":
        st.caption("Measured for your current focus (from shots recorded before and after it was set):")
        render_progress(progress)
    st.caption("Measured changes and your own reports are shown separately. They describe these recordings and "
               "don’t show that a practice caused a change.")


def comparison_side(player, column, label, recordings, sessions, summaries, key, default):
    with column:
        options = list(recordings)
        video_id = st.selectbox(label, options, index=min(default, len(options) - 1), key=f"{key}_recording",
                                format_func=lambda value: f"{short_name(recordings[value])} · "
                                                          f"{session_title(sessions.get(recordings[value]['session_id'], {'session_id': recordings[value]['session_id']}))}")
        recording = recordings[video_id]
        session = sessions.get(recording["session_id"], {})
        st.caption(f"{session.get('date') or 'Date unavailable'} · {attempt_count(recording['shot_count'])}")
        try:
            attempts = fetch_recordings(player, video_id).get("attempts", [])
        except requests.RequestException:
            attempts = []
        if not attempts:
            st.caption("Attempt details are unavailable.")
            return None, None
        if len(attempts) > 1:
            index = st.selectbox("Attempt", range(len(attempts)), key=f"{key}_attempt_{video_id}",
                                 format_func=lambda value: attempt_label(attempts[value]))
        else:
            index = 0
            st.caption(attempt_label(attempts[0]))
        return attempts[index], summaries.get(recording["session_id"])


def render_comparison(player, recordings, sessions, summaries):
    st.markdown("#### Compare recordings")
    by_id = {item["video_id"]: item for item in recordings if item.get("shot_count")}
    if len(by_id) < 2:
        st.caption("Comparison needs at least two analysed recordings.")
        return
    with st.container(key="progress_compare"):
        left, right = st.columns(2)
        first, first_summary = comparison_side(player, left, "First recording", by_id, sessions, summaries,
                                               f"compare_a_{player}", len(by_id) - 1)
        second, second_summary = comparison_side(player, right, "Second recording", by_id, sessions, summaries,
                                                 f"compare_b_{player}", 0)
        if not first or not second:
            return
        show_frames = st.toggle("Show matching frames", key=f"compare_frames_{player}")
        phase = st.segmented_control("Phase", list(COMPARE_PHASES), format_func=COMPARE_PHASES.get,
                                     key=f"compare_phase_{player}", default="release") if show_frames else None
        phase = phase or "release"
        for column, attempt in zip(st.columns(2) if show_frames else (), (first, second)):
            with column:
                frame = compare_frame(attempt, phase)
                image = frame_image(API_URL, player, attempt["shot_id"], frame[0]) if frame else None
                if image:
                    st.image(image, width="stretch")
                    st.caption(f"Attempt {attempt['shot_number']} · {COMPARE_PHASES[phase]} · "
                               f"{frame[1] / fps(attempt):.2f} s" if fps(attempt) else
                               f"Attempt {attempt['shot_number']} · {COMPARE_PHASES[phase]}")
                else:
                    st.caption("No matching frame is available for this attempt.")
        rows = []
        for field, label, unit in TECHNIQUE:
            values = [(attempt.get("biomechanics") or {}).get(field) for attempt in (first, second)]
            if all(value is not None for value in values):
                rows.append({"Measurement": label, "First": f"{values[0]:g}{unit}", "Second": f"{values[1]:g}{unit}"})
        if rows and same_conditions(first, second):
            st.dataframe(rows, hide_index=True, width="stretch")
        elif rows:
            st.caption("These attempts were recorded with a different shot type or arm, so their angles aren’t "
                       "compared.")
        for name, summary in (("First", first_summary), ("Second", second_summary)):
            if summary:
                known = summary["made"] + summary["missed"]
                st.caption(f"{name} session: {summary['made']} made of {known} confirmed outcomes · "
                           f"{summary['unknown']} unknown")
        st.button("Ask the coach to compare these attempts", icon=":material/compare_arrows:", width="stretch",
                  key="compare_ask", disabled=first["shot_id"] == second["shot_id"], on_click=set_tab,
                  args=("coach", f"Compare attempt {first['shot_number']} of {short_name(by_id[first['video_id']])} "
                                 f"with attempt {second['shot_number']} of {short_name(by_id[second['video_id']])}.",
                        [first["shot_id"], second["shot_id"]]))


def same_conditions(first, second):
    def conditions(attempt):
        return attempt.get("shot_type"), (attempt.get("biomechanics") or {}).get("shooting_arm")
    return conditions(first) == conditions(second)


def fps(attempt):
    events = attempt.get("shot_events") or {}
    if events.get("release_frame") and events.get("release_time_ms"):
        return events["release_frame"] / (events["release_time_ms"] / 1000)
    return None


def compare_frame(attempt, phase):
    events = attempt.get("shot_events") or {}
    frame = events.get("release_frame") if phase == "release" else (events.get("measurement_frames") or {}).get(phase)
    return (f"frame:{attempt['shot_id']}:{phase}:{frame}", frame) if frame is not None else None
