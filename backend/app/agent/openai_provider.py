"""OpenAI Responses API adapter for the shared coaching transcript."""

import os

from backend.app.agent.provider import HttpProvider, tool_definition

REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")


class OpenAIProvider(HttpProvider):
    def __init__(self, api_key, *, timeout=90, transport=None):
        super().__init__(
            base_url="https://api.openai.com/v1", headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout, transport=transport,
        )

    def respond(self, *, model, instructions, inputs, schema, tools=()):
        body = {
            "model": model, "instructions": instructions, "store": False,
            "input": [{key: value for key, value in item.items() if key != "name"}
                      if item.get("type") == "function_call_output" else item for item in inputs],
            "max_output_tokens": 4096, "include": ["reasoning.encrypted_content"],
        }
        if model.startswith("gpt-4"):
            body["temperature"] = 0.2
        else:
            # Reasoning models use their documented default unless an effort is configured.
            effort = (os.getenv("SHOTCOACH_REASONING_EFFORT") or "").strip().lower()
            if effort in REASONING_EFFORTS:
                body["reasoning"] = {"effort": effort}
        if schema is not None:
            body["text"] = {"format": {
                "type": "json_schema", "name": "shotcoach_response", "strict": False, "schema": schema,
            }}
        if tools:
            body["tools"] = [{"type": "function", "strict": False, **tool_definition(tool)} for tool in tools]
            body["parallel_tool_calls"] = True
        payload = self.request(model, "responses", body)
        if not isinstance(payload.get("output"), list):
            raise ValueError("Unexpected Responses API output")
        return payload["output"]
