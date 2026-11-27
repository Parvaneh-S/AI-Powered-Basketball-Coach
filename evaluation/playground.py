"""Development-only Streamlit UI for the real coach with synthetic evidence.

Run from the repository root:
    python -m streamlit run evaluation/playground.py --server.address 127.0.0.1 --server.port 8502
"""

import atexit
import importlib.util
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Lock
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
_STORE = None
_STORE_LOCK = Lock()


def initialize_runtime():
    """Select an empty temporary DB before importing any production DB module."""
    global _STORE
    with _STORE_LOCK:
        if _STORE is not None:
            assert_isolated_runtime()
            return
        if "backend.app.database.models" in sys.modules:
            raise RuntimeError("Start the playground in a fresh, separate Python process; production database modules are already loaded.")
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        temporary = tempfile.TemporaryDirectory(prefix="shotcoach_playground_")
        directory = Path(temporary.name).resolve()
        if not directory.is_relative_to(Path(tempfile.gettempdir()).resolve()):
            raise RuntimeError("Playground storage must stay inside the temporary directory.")
        path = directory / "synthetic_coaching.db"
        # Existing models copy the demo seed if a DB does not exist. Touch an
        # empty SQLite DB first so no real/demo player rows are imported.
        sqlite3.connect(path).close()
        os.environ["SHOTCOACH_DB_PATH"] = str(path)
        from backend.app.database import models
        from backend.app.agent import memory  # register the existing memory table
        models.Base.metadata.create_all(models.engine)
        _STORE = (temporary, path)
        def cleanup():
            models.engine.dispose()
            temporary.cleanup()
        atexit.register(cleanup)


def assert_isolated_runtime():
    if _STORE is None:
        raise RuntimeError("Initialize the dedicated playground process first.")
    from backend.app.database import models
    if models.DB_PATH.resolve() != _STORE[1] or Path(models.engine.url.database).resolve() != _STORE[1]:
        raise RuntimeError("Refusing to use a database outside the isolated playground store.")


def connectivity_status():
    """Report readiness only; never expose keys, proxy URLs or configuration dumps."""
    proxy_names = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
    socks = any(os.getenv(name, "").lower().startswith(("socks5:", "socks5h:", "socks4:")) for name in proxy_names)
    socks_support = importlib.util.find_spec("socksio") is not None
    from backend.app.agent.provider import provider_settings
    try:
        settings = provider_settings()
    except ValueError:
        return {"key_configured": False, "socks_proxy_detected": socks,
                "socks_support_installed": socks_support, "readiness": "invalid_provider_configuration"}
    configured = bool(settings.key)
    return {"key_configured": configured, "socks_proxy_detected": socks,
            "socks_support_installed": socks_support,
            "readiness": "missing_key" if not configured else "missing_socks_support" if socks and not socks_support else "ready_to_attempt",
            "note": "Readiness is not a successful provider connection. Live calls use production networking unchanged."}


def start_scenario(key):
    assert_isolated_runtime()
    from evaluation.fixtures import playground_scenario
    from backend.app.agent.memory import save_memory
    case = playground_scenario(key, "SYNTHETIC_" + uuid4().hex)
    if not save_memory(case["player"], "", case["memory"]):
        raise RuntimeError("Could not initialize synthetic practice memory.")
    return case


def apply_settings(case, experience, style, seconds, equipment, easier):
    assert_isolated_runtime()
    from backend.app.agent.memory import read_memory, save_memory
    revision, memory = read_memory(case["player"])
    practice = {"equipment": {key: value for key, value in equipment.items() if value is not None}}
    if seconds is not None:
        practice["available_time_seconds"] = seconds
    if easier:
        practice["easier"] = True
    preferences = {**memory.get("preferences", {}), "practice": practice}
    if style:
        preferences["explanation_style"] = style
    else:
        preferences.pop("explanation_style", None)
    if not save_memory(case["player"], revision, {**memory, "experience": experience, "preferences": preferences}):
        raise RuntimeError("Synthetic context changed; apply the settings again.")


def ask_scenario(case, question, history=()):
    """No mock client or alternate response generator: invoke the production coach."""
    assert_isolated_runtime()
    if not case["player"].startswith("SYNTHETIC_") or not case["shots"] or any(
        shot.player != case["player"] or shot.analysis.get("synthetic") is not True for shot in case["shots"]
    ):
        raise ValueError("The playground accepts explicitly synthetic evidence only.")
    from backend.app.agent.coaching_agent import coach
    return coach(case["player"], question, selected=case["shots"][0].shot_id,
                 session_id=1, shots=case["shots"], history=history,
                 multimodal=False, persist=True)


def show_response(st, result, player, key):
    from frontend.coaching import render_response
    provenance = result.get("provenance") or {}
    if provenance.get("wording") == "model_authored":
        st.caption("Model-authored coaching accepted by the local validators.")
    else:
        st.warning("Server-rendered response, not model-authored coaching. Source: "
                   + str(provenance.get("source")) + "; reason: " + str(provenance.get("reason")))
    render_response(result, player, "", key)
    with st.expander("Debug — separate from player-facing coaching"):
        st.json({"provenance": provenance,
                 "selected_priority": provenance.get("selected_topic"),
                 "supporting_evidence": {"ids": provenance.get("supporting_evidence_ids", []),
                     "observations": result.get("observations", []), "strengths": result.get("strengths", []),
                     "authored_evidence": result.get("authored_evidence")},
                 "validation_failures": provenance.get("validation_failures", []),
                 "fallback_reason": provenance.get("reason"),
                 "selected_exercise": result.get("practice")})


def main():
    import streamlit as st
    st.set_page_config(page_title="Synthetic Coaching Playground", page_icon="🏀", layout="wide")
    st.title("Coaching testing playground")
    st.warning("DEVELOPMENT ONLY — all analysis, outcomes and players here are SYNTHETIC. No video is uploaded, generated or processed.")
    try:
        initialize_runtime()
    except RuntimeError as error:
        st.error(str(error))
        st.stop()
    from evaluation.fixtures import PLAYGROUND_SCENARIOS
    from backend.app.agent.memory import read_memory
    from backend.app.agent.retrieval import CoachingTools
    from backend.app.agent.coaching_agent import response_text

    with st.expander("Coaching provider connectivity and setup"):
        status = connectivity_status()
        st.json(status)
        if status["readiness"] == "missing_key":
            st.info("Set the selected provider key in the project .env file, then restart this playground process.")
        elif status["readiness"] == "missing_socks_support":
            st.error("The host configures a SOCKS proxy but its optional socksio dependency is missing. Live coaching cannot initialize.")
            st.code("python -m pip install socksio", language="powershell")
            st.caption("Run this only in your project virtual environment if that proxy is required. Restart afterward. The playground does not disable proxies or TLS verification.")
        else:
            st.caption("Ask a question to test the real generation and review calls. Provider errors remain clearly labelled fallbacks.")

    scenario = st.selectbox("Synthetic scenario", list(PLAYGROUND_SCENARIOS),
                            format_func=lambda key: PLAYGROUND_SCENARIOS[key][0], key="playground_scenario")
    if ("playground_case" not in st.session_state
            or st.session_state.playground_case["key"] != scenario):
        st.session_state.playground_case = start_scenario(scenario)
        st.session_state.playground_messages = []
    case = st.session_state.playground_case
    st.write(case["description"])
    st.caption("Scenario changes start a new isolated player and conversation. Memory is temporary and separate from real players. This tests the coach, not analysis accuracy.")

    with st.expander("Player context and constraints"):
        with st.form("playground_settings_" + case["player"]):
            experience = st.selectbox("Experience", ["Unknown", "beginner", "intermediate", "experienced", "advanced"])
            style = st.selectbox("Explanation preference", ["Unspecified", "simple", "detailed"])
            limited = st.checkbox("Specify available practice time")
            seconds = st.number_input("Practice time in seconds", min_value=0, max_value=3600, value=120, step=15)
            choices = {"Unknown": None, "Available": True, "Unavailable": False}
            equipment = {resource: choices[st.selectbox(label, list(choices))] for resource, label in (
                ("ball", "Ball"), ("hoop", "Hoop"), ("camera", "Camera"), ("clear_space", "Clear stable space"))}
            easier = st.checkbox("Request an easier exercise")
            if st.form_submit_button("Apply synthetic player context"):
                apply_settings(case, "" if experience == "Unknown" else experience,
                               "" if style == "Unspecified" else style, int(seconds) if limited else None, equipment, easier)
                st.success("Synthetic context saved. Ask your next question.")
        memory = read_memory(case["player"])[1]
        st.json({"experience": memory["experience"], "preferences": memory["preferences"],
                 "current_practice": memory["recommendations"][-1:] , "practice_reports": memory["reports"][-4:]})

    with st.expander("Synthetic analysis inputs — no video evidence"):
        summary = CoachingTools(case["player"], shots=case["shots"], session_id=1).session_summary()
        st.json({"data_origin": case["data_origin"], "session_summary": summary})
        st.dataframe([{"shot": shot.shot_number, "outcome": shot.outcome,
                       **{key: shot.analysis["biomechanics"].get(key) for key in (
                           "min_knee_angle", "release_elbow_angle", "shooting_motion_ms", "measurement_quality",
                           "knee_coverage_pct", "elbow_coverage_pct")}} for shot in case["shots"]], hide_index=True)
    st.caption("Try: What am I doing well? · Why am I missing? · What should I practise? · I have no hoop; suggest something easier.")
    messages = st.session_state.playground_messages
    for index, message in enumerate(messages):
        with st.chat_message(message["role"]):
            if message["role"] == "assistant":
                show_response(st, message["coaching"], case["player"], f"synthetic_{index}")
            else:
                st.write(message["content"])
    question = st.chat_input("Ask any coaching question using this synthetic session", max_chars=2000)
    if question and question.strip():
        with st.spinner("Running the coaching pipeline…"):
            try:
                result = ask_scenario(case, question.strip(), [{"role": item["role"], "content": item["content"]}
                                                              for item in messages[-10:]])
            except Exception as error:
                # Do not render raw SDK exceptions, environment values or credentials.
                logging.getLogger(__name__).warning("Playground request failed (%s)", type(error).__name__)
                st.error("The playground request failed before a validated response was returned. Check the local terminal; no raw exception is displayed here.")
            else:
                messages.extend([{"role": "user", "content": question.strip()},
                                 {"role": "assistant", "content": response_text(result),
                                  "coaching": result.model_dump(mode="json")}])
                st.session_state.playground_messages = messages[-24:]
                st.rerun()
    if st.button("Reset this synthetic player and conversation"):
        st.session_state.playground_case = start_scenario(scenario)
        st.session_state.playground_messages = []
        st.rerun()


def check_provider():
    """Check text generation and authored coaching using fictional data."""
    initialize_runtime()
    from backend.app.agent.provider import provider_diagnostic
    status = connectivity_status()
    print("Coaching provider readiness:", status)
    if status["readiness"] != "ready_to_attempt":
        return 1
    try:
        result = ask_scenario(start_scenario("consistent_high"), "What am I doing well?")
        p = result.provenance
        print({key: p.get(key) for key in ("provider", "source", "wording", "reason", "provider_failure", "validation_failures")})
        return 0 if p["wording"] == "model_authored" else 1
    except Exception as exc:
        print(provider_diagnostic(exc, "synthetic_coaching"))
        return 1


if __name__ == "__main__":
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    # Use the canonical module so the temporary store survives Streamlit reruns.
    if sys.argv[1:] == ["--check-provider"]:
        raise SystemExit(check_provider())
    from evaluation.playground import main as run_playground
    run_playground()
