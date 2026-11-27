"""Opt-in local diagnostics for coaching development."""

import json
import logging
import math
import os
import re
from contextlib import contextmanager
from contextvars import ContextVar


active_trace = ContextVar("shotcoach_active_trace", default=None)


def model_pricing():
    try:
        rates = json.loads(os.getenv("SHOTCOACH_MODEL_PRICING") or os.getenv("SHOTCOACH_OPENAI_PRICING", "{}"),
                           parse_int=float)
    except ValueError:
        return {}
    return rates if isinstance(rates, dict) else {}


def token_count(value):
    return value if type(value) is int and value >= 0 else None


class CoachingTrace:
    def __init__(self):
        self.enabled = os.getenv("SHOTCOACH_DEBUG") == "1"
        self.events = []
        self.source = "fallback"
        self.reason = None
        self.provider_stage = "client_initialization"
        self.provider_failure = None
        self.validation_failures = []
        self.discarded_components = []
        self.requests = []
        self.pricing = model_pricing()

    @contextmanager
    def track_requests(self):
        token = active_trace.set(self)
        try:
            yield
        finally:
            active_trace.reset(token)

    def record_request(self, requested_model, payload, latency_ms):
        payload = payload if isinstance(payload, dict) else {}
        returned_model = payload.get("model")
        model = returned_model if isinstance(returned_model, str) and returned_model else requested_model
        usage = payload.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        details = usage.get("input_tokens_details")
        details = details if isinstance(details, dict) else {}
        input_tokens = token_count(usage.get("input_tokens"))
        cached_input_tokens = token_count(details.get("cached_tokens"))
        output_tokens = token_count(usage.get("output_tokens"))
        if input_tokens is not None and cached_input_tokens is not None and cached_input_tokens > input_tokens:
            cached_input_tokens = None
        rates = self.pricing.get(model, self.pricing.get(requested_model))
        cost = None
        if isinstance(rates, dict) and all(
            type(rates.get(field)) is float and math.isfinite(rates[field]) and rates[field] >= 0
            for field in ("input", "cached_input", "output")
        ) and input_tokens is not None and output_tokens is not None and (
            cached_input_tokens is not None or input_tokens == 0 or rates["input"] == rates["cached_input"]
        ):
            cached = cached_input_tokens or 0
            estimate = ((input_tokens - cached) * (rates["input"] / 1_000_000)
                        + cached * (rates["cached_input"] / 1_000_000)
                        + output_tokens * (rates["output"] / 1_000_000))
            if math.isfinite(estimate):
                cost = round(estimate, 8)
        self.requests.append({
            "model": model,
            "purpose": "repair" if self.provider_stage == "repair_generation" else self.provider_stage,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": cost,
            "latency_ms": round(latency_ms, 3),
        })

    def request_usage(self):
        costs = [entry["estimated_cost_usd"] for entry in self.requests]
        return {"total_requests": len(costs),
                "estimated_cost_usd": round(sum(costs), 8) if all(cost is not None for cost in costs) else None,
                "requests": self.requests}

    def mark_last_request(self, purpose):
        if self.requests:
            self.requests[-1]["purpose"] = purpose

    def add(self, stage, **data):
        if self.enabled:
            self.events.append({"stage": stage, **data})

    def finish(self):
        if not self.enabled:
            return
        message = json.dumps({"source": self.source, "events": self.events,
                              "request_usage": self.request_usage()}, ensure_ascii=False, default=str)
        for name, value in os.environ.items():
            if len(value) >= 8 and any(marker in name.upper() for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
                message = message.replace(json.dumps(value, ensure_ascii=False)[1:-1], "[redacted]")
        message = re.sub(r"AIza[A-Za-z0-9_-]{30,}|(?i:bearer)\s+[A-Za-z0-9._-]{12,}", "[redacted]", message)
        logging.getLogger(__name__).warning("ShotCoach development trace %s", message)
