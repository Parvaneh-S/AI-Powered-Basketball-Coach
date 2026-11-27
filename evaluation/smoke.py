"""Start both local services and exercise the demo coaching routes over HTTP."""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]


def pick_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def ready(url, process):
    for _ in range(60):
        if process.poll() is not None:
            raise RuntimeError("A local service exited during startup.")
        try:
            if requests.get(url, timeout=1).ok:
                return
        except requests.RequestException:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Local service did not start: {url}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation" / "smoke-results.json")
    args = parser.parse_args()
    api_port, frontend_port = pick_port(), pick_port()
    while api_port == frontend_port:
        frontend_port = pick_port()
    api = f"http://127.0.0.1:{api_port}"
    env = os.environ.copy()
    env["OPENAI_API_KEY"] = ""
    env["GEMINI_API_KEY"] = ""
    env["SHOTCOACH_API_URL"] = api
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with tempfile.TemporaryDirectory(prefix="shotcoach_smoke_") as folder:
        env["SHOTCOACH_DB_PATH"] = str(Path(folder) / "demo.db")
        log_path = Path(folder) / "services.log"
        with log_path.open("w", encoding="utf-8") as logs:
            commands = [
                ["-m", "uvicorn", "backend.app.api.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
                ["-m", "streamlit", "run", "frontend/app.py", "--server.address=127.0.0.1",
                 f"--server.port={frontend_port}", "--server.headless=true", "--browser.gatherUsageStats=false"],
            ]
            processes = []
            try:
                for command in commands:
                    processes.append(subprocess.Popen([sys.executable, *command], cwd=ROOT, env=env,
                                                      stdout=logs, stderr=logs, creationflags=flags))
                ready(f"{api}/api/health", processes[0])
                ready(f"http://127.0.0.1:{frontend_port}/_stcore/health", processes[1])
                player = {"player_name": "TestPlayer"}
                answer = requests.post(f"{api}/api/coach/ask", timeout=15, json={
                    **player, "selected_shot_id": "free_throw_03",
                    "question": "Can you show me my follow through?",
                })
                answer.raise_for_status()
                refs = answer.json()["coaching"]["video_references"]
                assert len(refs) == 2
                for ref in refs:
                    query = {**player, "shot_id": ref["shot_id"], "reference_id": ref["id"]}
                    frame = requests.get(f"{api}/api/coach/frame", params=query, timeout=5)
                    assert frame.status_code == 200 and frame.content.startswith(b"\xff\xd8")
                    denied = requests.get(f"{api}/api/coach/frame", timeout=5,
                                          params={**query, "player_name": "Different player"})
                    assert denied.status_code == 404
                practice = requests.post(f"{api}/api/coach/ask", timeout=15, json={
                    **player, "selected_shot_id": "free_throw_03",
                    "question": "What should I practice for knee bend?",
                })
                practice.raise_for_status()
                focus = practice.json()["coaching"]["memory_update"]
                report = requests.patch(f"{api}/api/coach/memory", params=player, timeout=10,
                                        json={"focus_id": focus["id"], "report_kind": "completed"})
                report.raise_for_status()
                memory = requests.get(f"{api}/api/coach/memory", params=player, timeout=10)
                memory.raise_for_status()
                assert memory.json()["reports"][-1]["kind"] == "completed"
                result = {"api_ready": True, "streamlit_ready": True,
                          "demo_video": "free_throw_03", "decoded_frames": refs,
                          "cross_player_frame_rejected": True, "practice_logged": True,
                          "fresh_upload": "not run in this smoke test", "live_openai_requests": 0}
            finally:
                for process in processes:
                    process.terminate()
                for process in processes:
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("FastAPI and Streamlit were reachable. The demo returned real frames and stored a practice report.")


if __name__ == "__main__":
    main()
