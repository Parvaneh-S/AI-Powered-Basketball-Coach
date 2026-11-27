"""Reproduce the generic-response fix using fictional shooting data only."""

import argparse
import json
import logging
import os
from pathlib import Path
from unittest.mock import patch

from backend.app.agent.provider import provider_settings

from backend.app.agent.coaching_agent import coach, response_text
from backend.app.agent.context import EvidenceContext
from backend.app.agent.memory import empty_memory
from evaluation.fixtures import MockOpenAI, synthetic_shot

QUESTION = "What should I practice for my shooting arm?"


def patterns(higher):
    return [synthetic_shot(i, outcome="made" if i <= 6 else "missed",
                           angle=(145 if (i <= 6) == higher else 105) + i % 3)
            for i in range(1, 13)]


def draft_for(shots):
    ctx = EvidenceContext("Fixture", QUESTION, "fixture_shot_1", (), [], empty_memory(), shots=shots)
    ctx.collect(multimodal=False)
    key = next(key for key in ctx.observations if key.startswith("pattern:release_elbow_angle:"))
    return {"message": "A slightly straighter release gives us one position to test. The pattern does not explain why shots missed.",
            "knowledge_ids": ["arm"], "evidence_ids": [key], "practice": {
                "topic": "arm", "drill_id": "focused_shooting",
                "instructions": "Start close and let your elbow unfold comfortably through a short set.",
                "evaluation": "Film from the same side and compare release position and recorded outcomes separately.",
            }}


def run_case(label, shots, client=None):
    with patch("backend.app.agent.retrieval.load_shots", return_value=shots), patch(
        "backend.app.agent.retrieval.shot_frames", return_value=[]
    ):
        result = coach("Fixture", QUESTION, selected="fixture_shot_1", client=client, multimodal=False,
                       persist=False, memory_state=("", empty_memory()))
    return {"path": label, "text": response_text(result), "response": result.model_dump(mode="json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send fictional shot evidence only, with no images.")
    parser.add_argument("--output", type=Path, default=Path("evaluation/coaching-generic-after.json"))
    args = parser.parse_args()
    higher = patterns(True)
    with patch.dict(os.environ, {"OPENAI_API_KEY": "", "GEMINI_API_KEY": ""}):
        report = {"question": QUESTION, "data": "synthetic fixtures only", "runs": [
            run_case("fallback, same fixture as before", [synthetic_shot()]),
            run_case("fallback, straighter elbow on makes", higher),
            run_case("fallback, more bent elbow on makes", patterns(False)),
            run_case("mocked author turn", higher, MockOpenAI([draft_for(higher)])),
        ]}
    settings = provider_settings()
    if args.live and settings.key:
        logger = logging.getLogger("backend.app.agent.diagnostics")

        class Capture(logging.Handler):
            def emit(self, record):
                message = record.getMessage()
                _, _, data = message.partition("ShotCoach development trace ")
                if data:
                    report["live_trace"] = json.loads(data)

        handler = Capture()
        logger.addHandler(handler)
        original_propagation = logger.propagate
        logger.propagate = False
        try:
            with patch.dict(os.environ, {"SHOTCOACH_DEBUG": "1"}), settings.connect(timeout=20) as client:
                report["runs"].append(run_case("live OpenAI attempt on synthetic evidence", higher, client))
        finally:
            logger.removeHandler(handler)
            logger.propagate = original_propagation
    elif args.live:
        report["live_status"] = "Provider key unavailable"
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {len(report['runs'])} runs. Live source: "
          f"{report.get('live_trace', {}).get('source', report.get('live_status', 'not requested'))}.")


if __name__ == "__main__":
    main()
