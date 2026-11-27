"""Shared provider interface, configuration, and bounded tool invocation."""

import base64
import json
import os
from dataclasses import dataclass, field
from inspect import Parameter, signature
from time import perf_counter
from typing import Protocol

import httpx
from pydantic import TypeAdapter

from backend.app.agent.diagnostics import active_trace

PROVIDER_ERRORS = (httpx.HTTPError,)


class CoachingProvider(Protocol):
    """Respond to a shared transcript of text, images, tool calls and tool results."""

    def respond(self, *, model, instructions, inputs, schema, tools=()) -> list[dict]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    model: str
    key_env: str
    key: str = field(repr=False)

    def connect(self, **kwargs) -> CoachingProvider:
        if self.name == "gemini":
            from backend.app.agent.gemini_provider import GeminiProvider
            return GeminiProvider(self.key, **kwargs)
        from backend.app.agent.openai_provider import OpenAIProvider
        return OpenAIProvider(self.key, **kwargs)


def provider_settings():
    name = (os.getenv("SHOTCOACH_PROVIDER") or "openai").strip().lower()
    if name == "openai":
        model_env, default, key_env = "OPENAI_MODEL", "gpt-4.1-mini", "OPENAI_API_KEY"
    elif name == "gemini":
        model_env, default, key_env = "GEMINI_MODEL", "gemini-3.6-flash", "GEMINI_API_KEY"
    else:
        raise ValueError("Unsupported coaching provider")
    model = os.getenv("SHOTCOACH_MODEL") or os.getenv(model_env) or default
    return ProviderSettings(name, model.strip() or default, key_env, os.getenv(key_env, ""))


def provider_diagnostic(exc, stage):
    detail = {"stage": stage, "exception": type(exc).__name__}
    if isinstance(exc, httpx.HTTPStatusError):
        detail["http_status"] = exc.response.status_code
    elif isinstance(exc, ImportError) and "socksio" in str(exc).lower():
        detail["transport_reason"] = "missing_socks_support"
    return detail


def text_part(text):
    return {"type": "input_text", "text": text}


def image_part(jpeg):
    encoded = base64.b64encode(jpeg).decode("ascii")
    return {"type": "input_image", "image_url": f"data:image/jpeg;base64,{encoded}", "detail": "auto"}


def output_text(output):
    return "".join(part["text"] for item in output if item["type"] == "message"
                   for part in item["content"] if part["type"] == "output_text")


def tool_definition(tool):
    parameters = signature(tool).parameters
    return {
        "name": tool.__name__, "description": tool.__doc__ or "",
        "parameters": {
            "type": "object", "additionalProperties": False,
            "properties": {name: TypeAdapter(parameter.annotation).json_schema()
                           for name, parameter in parameters.items()},
            "required": [name for name, parameter in parameters.items() if parameter.default is Parameter.empty],
        },
    }


def run_tool(tool, arguments):
    if tool is None:
        return {"status": "unavailable"}
    try:
        bound = signature(tool).bind(**json.loads(arguments))
        for name, value in bound.arguments.items():
            TypeAdapter(signature(tool).parameters[name].annotation).validate_python(value, strict=True)
    except (TypeError, ValueError):
        return {"status": "invalid_arguments"}
    return tool(**bound.arguments)


class HttpProvider:
    """Shared HTTP lifecycle and request metering for the two transports."""

    def __init__(self, **options):
        self.http = httpx.Client(**options)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.http.close()

    def request(self, model, path, body):
        trace = active_trace.get()
        started = perf_counter()
        payload = {}
        try:
            response = self.http.post(path, json=body)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Unexpected coaching provider response")
            return payload
        finally:
            if trace is not None:
                trace.record_request(model, self.usage(payload if isinstance(payload, dict) else {}),
                                     (perf_counter() - started) * 1000)

    def usage(self, payload):
        return payload
