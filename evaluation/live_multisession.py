"""One live multi-session conversation on synthetic fixture sessions, with a hard spending cap.

Usage: python -m evaluation.live_multisession [--budget 0.10]
Three fictional sessions (3, 5 and 8 makes of 10, tightening release angle) and a saved knee plan.
Memory is never written; a player's chat report is applied to the next turn's memory as the app would save it.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from backend.app.agent.coaching_agent import coach, response_text  # noqa: E402
from backend.app.agent.memory import empty_memory  # noqa: E402
from backend.app.agent.provider import provider_settings  # noqa: E402
from evaluation.fixtures import fixture_focus, synthetic_shot  # noqa: E402
from evaluation.live_investigative import CappedProvider  # noqa: E402

PLAYER = "SYNTHETIC_multisession"
TURNS = [
    ("What do you remember about my shooting so far?", None),
    ("Did the knee drill you gave me help?", None),
    ("Honestly it didn't help, the knee cue felt awkward. What now?", "did_not_help"),
    ("My shot does feel smoother lately though. Have I actually improved?", None),
    ("What should I work on next?", None),
]


def fixture():
    shots = [synthetic_shot((session - 1) * 10 + index + 1, player=PLAYER, session_id=session,
                            outcome="made" if index < makes else "missed",
                            angle=125 + spread * (-1 if index % 2 else 1))
             for session, (makes, spread) in enumerate(((3, 9), (5, 5), (8, 2)), start=1) for index in range(10)]
    focus = {**fixture_focus(shots[:10]), "session_id": 1, "drill_id": "focused_shooting",
             "prescribed_dose": {"sets": 1, "repetitions": 5, "duration_seconds": 75},
             "practice_instructions": "Use the same comfortable knee bend before each attempt.",
             "recorded_at": "2026-11-20T00:00:00+00:00"}
    routine = {"title": "Shooting consistency", "knowledge_id": "routine", "decision": "start", "evidence_ids": [],
               "cue": "Set your feet, pick a spot on the rim, then use the same comfortable rhythm each time.",
               "recorded_at": "2026-11-15T00:00:00+00:00"}
    memory = {**empty_memory(), "goal": "Make 7 of 10 free throws", "experience": "intermediate",
              "recommendations": [{**routine, "id": "routine_1"}, {**routine, "id": "routine_2"}, focus]}
    return shots, focus, memory


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=0.10)
    parser.add_argument("--reserve", type=float, default=0.03)
    parser.add_argument("--output", default="evaluation/live-terra-multisession.json")
    args = parser.parse_args()
    settings = provider_settings()
    shots, focus, memory = fixture()
    history, turns = [], []
    with CappedProvider(settings.key, args.budget, args.reserve) as client:
        for number, (question, report) in enumerate(TURNS, 1):
            start, started = len(client.log), time.perf_counter()
            result = coach(PLAYER, question, shots=shots, selected=shots[-1].shot_id, history=history,
                           client=client, persist=False, memory_state=("", memory))
            text = response_text(result)
            turns.append({"question": question, "seconds": round(time.perf_counter() - started, 2),
                          "player_text": text, "progress": result.progress,
                          "practice": result.practice.model_dump() if result.practice else None,
                          "memory_update": result.memory_update,
                          "provenance": {k: v for k, v in (result.provenance or {}).items() if k != "request_usage"},
                          "requests": client.log[start:]})
            print(f"\n=== {number}. {question}  [{result.provenance['source']}] "
                  f"discarded={result.provenance['discarded_components']}  spent ${client.spent:.4f}\n{text}")
            history += [{"role": "user", "content": question}, {"role": "assistant", "content": text}]
            if report:  # What the app saves when the player reports in chat.
                memory = {**memory, "reports": [*memory["reports"],
                                                {"focus_id": focus["id"], "kind": report, "text": question}]}
    Path(args.output).write_text(json.dumps({"model": settings.model, "turns": turns,
                                             "estimated_cost_usd": round(client.spent, 6)}, indent=2),
                                 encoding="utf-8")
    print(f"\nTotal estimated cost ${client.spent:.4f}; saved {args.output}")


if __name__ == "__main__":
    main()
