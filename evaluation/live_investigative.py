"""One live four-turn conversation on free_throw_02 with a hard spending cap.

Usage: python -m evaluation.live_investigative [--budget 0.25]
Uses the configured production provider and model. Memory is read but never written.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from backend.app.agent.coaching_agent import coach, response_text  # noqa: E402
from backend.app.agent.openai_provider import OpenAIProvider  # noqa: E402
from backend.app.agent.provider import provider_settings  # noqa: E402
from backend.app.api.coaching import get_coaching_frame  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PLAYER, SHOT_ID = "TestPlayer", "free_throw_02_shot_1"
INTERACTIVE = [
    "Why did I miss this shot?",
    "Yes, it felt a little flat and short coming off my hand, like I rushed the release.",
    "Can you visually show me what I should improve?",
    "What should I practice, and can you recommend an instructional video?",
    "What should I keep about my current technique?",
]
QUESTIONS = [
    "Why did I miss this shot?",
    "Can you visually show me what I should improve?",
    "What should I practice, and can you recommend an instructional video?",
    "What should I keep about my current technique?",
]
# Conservative USD per million tokens: uncached input at the cache-write rate.
RATES = {"input": 1.25, "cached_input": 0.05, "output": 5.00}
# Largest plausible single request: 30k uncached input tokens and the full 4,096-token output cap.
RESERVE = (30_000 * RATES["input"] + 4096 * RATES["output"]) / 1e6


class BudgetExceeded(ValueError):
    pass


class CappedProvider(OpenAIProvider):
    def __init__(self, key, budget, reserve=RESERVE):
        super().__init__(key)
        self.budget, self.reserve, self.spent, self.log = budget, reserve, 0.0, []

    def request(self, model, path, body):
        if self.spent + self.reserve > self.budget:
            raise BudgetExceeded("Live evaluation budget reached")
        started = time.perf_counter()
        payload = super().request(model, path, body)
        usage = payload.get("usage") or {}
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
        cost = ((usage.get("input_tokens", 0) - cached) * RATES["input"] + cached * RATES["cached_input"]
                + usage.get("output_tokens", 0) * RATES["output"]) / 1e6
        self.spent += cost
        self.log.append({
            "model": payload.get("model"), "seconds": round(time.perf_counter() - started, 2),
            "input_tokens": usage.get("input_tokens"), "cached_tokens": cached,
            "output_tokens": usage.get("output_tokens"),
            "reasoning_tokens": (usage.get("output_tokens_details") or {}).get("reasoning_tokens"),
            "cost_usd": round(cost, 6), "reasoning": body.get("reasoning"),
            "images_sent": sum(1 for item in body["input"] if isinstance(item, dict)
                               for part in item.get("content", []) if isinstance(part, dict)
                               and part.get("type") == "input_image"),
            "tools_offered": len(body.get("tools", [])),
            "output": [{key: item.get(key) for key in ("type", "name", "arguments")} if item.get("type") == "function_call"
                       else {"type": "message", "text": "".join(part.get("text", "") for part in item.get("content", []))}
                       for item in payload.get("output", []) if item.get("type") in ("function_call", "message")],
        })
        return payload


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=0.25)
    parser.add_argument("--output", default="evaluation/live-terra-investigative.json")
    parser.add_argument("--reserve", type=float, default=RESERVE, help="worst-case USD for one request")
    parser.add_argument("--interactive", action="store_true", help="include the player's answer to the coach")
    args = parser.parse_args()
    settings = provider_settings()
    if settings.name != "openai" or not settings.key:
        raise SystemExit("Configure OPENAI_API_KEY and the OpenAI provider first.")
    frames_dir = ROOT / "evaluation" / (Path(args.output).stem + "-frames")
    frames_dir.mkdir(parents=True, exist_ok=True)
    history, turns = [], []
    with CappedProvider(settings.key, args.budget, args.reserve) as client:
        for number, question in enumerate(INTERACTIVE if args.interactive else QUESTIONS, 1):
            start = len(client.log)
            started = time.perf_counter()
            result = coach(PLAYER, question, selected=SHOT_ID, history=history, client=client, persist=False)
            text = response_text(result)
            frames = []
            for ref in result.video_references:
                path = frames_dir / f"turn-{number}-{ref['id'].replace(':', '_')}.jpg"
                response = get_coaching_frame(PLAYER, ref.get("shot_id", SHOT_ID), ref["id"])
                path.write_bytes(response.body)
                frames.append({**ref,
                               "file": str(path.relative_to(ROOT))})
            turns.append({
                "question": question, "seconds": round(time.perf_counter() - started, 2),
                "player_text": text, "frames": frames,
                "resource": result.instructional_resource.model_dump() if result.instructional_resource else None,
                "practice": result.practice.model_dump() if result.practice else None,
                "provenance": {key: value for key, value in (result.provenance or {}).items() if key != "request_usage"},
                "requests": client.log[start:],
            })
            print(f"\n=== {number}. {question}  [{result.provenance['source']}]  spent ${client.spent:.4f}\n{text}")
            history += [{"role": "user", "content": question}, {"role": "assistant", "content": text}]
    report = {"model": settings.model, "player": PLAYER, "shot_id": SHOT_ID, "budget_usd": args.budget,
              "estimated_cost_usd": round(client.spent, 6), "turns": turns}
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nTotal estimated cost ${client.spent:.4f}; saved {args.output}")


if __name__ == "__main__":
    main()
