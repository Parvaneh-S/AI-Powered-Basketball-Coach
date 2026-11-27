"""Gemini REST adapter for the shared coaching transcript."""

import json
import re

from backend.app.agent.provider import HttpProvider, tool_definition


class GeminiProvider(HttpProvider):
    def __init__(self, api_key, *, timeout=90, transport=None):
        super().__init__(base_url="https://generativelanguage.googleapis.com/v1beta/",
                         headers={"x-goog-api-key": api_key}, timeout=timeout, transport=transport)

    def respond(self, *, model, instructions, inputs, schema, tools=()):
        if not re.fullmatch(r"(?:models/)?[a-zA-Z0-9_.-]+", model):
            raise ValueError("Invalid Gemini model identifier")
        model = model.removeprefix("models/")
        config = {"maxOutputTokens": 4096}
        body = {"contents": self.contents(inputs), "generationConfig": config}
        if tools:
            # Some Gemini versions cannot combine JSON mode with function declarations.
            declarations = []
            for tool in tools:
                definition = tool_definition(tool)
                definition["parametersJsonSchema"] = definition.pop("parameters")
                declarations.append(definition)
            body["tools"] = [{"functionDeclarations": declarations}]
            if schema is not None:
                instructions += ("\nWhen answering rather than calling a tool, return only a JSON object with a message. "
                                 "Optional fields must match this schema: " + json.dumps(schema, separators=(",", ":")))
        elif schema is not None:
            config.update(responseMimeType="application/json", responseJsonSchema=schema)
        body["systemInstruction"] = {"parts": [{"text": instructions}]}
        payload = self.request(model, f"models/{model}:generateContent", body)
        candidate = (payload.get("candidates") or [{}])[0]
        if candidate.get("finishReason") not in (None, "STOP", "MAX_TOKENS"):
            return []
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        if not parts:
            return []
        # Keep the original model parts for the next turn, including opaque thought signatures.
        output = [{"type": "gemini_content", "content": content}]
        for index, part in enumerate(parts):
            if call := part.get("functionCall"):
                output.append({"type": "function_call", "name": call["name"],
                               "call_id": call.get("id") or f"gemini_{len(inputs)}_{index}",
                               "arguments": json.dumps(call.get("args", {}))})
            elif "text" in part and not part.get("thought"):
                output.append({"type": "message", "content": [{"type": "output_text", "text": part["text"]}]})
        return output

    @staticmethod
    def contents(inputs):
        contents, native_ids = [], set()
        for item in inputs:
            if item.get("type") == "gemini_content":
                contents.append(item["content"])
                native_ids.update(part["functionCall"]["id"] for part in item["content"]["parts"]
                                  if part.get("functionCall", {}).get("id"))
            elif item.get("type") == "function_call_output":
                result = {"name": item["name"], "response": json.loads(item["output"])}
                if item["call_id"] in native_ids:
                    result["id"] = item["call_id"]
                part = {"functionResponse": result}
                previous = contents[-1] if contents else {}
                if previous.get("role") == "user" and all("functionResponse" in p for p in previous["parts"]):
                    # Responses to several calls from one model turn belong in one user turn.
                    previous["parts"].append(part)
                else:
                    contents.append({"role": "user", "parts": [part]})
            elif item.get("role") == "user":
                contents.append({"role": "user", "parts": [
                    {"text": part["text"]} if part["type"] == "input_text" else
                    {"inlineData": {"mimeType": "image/jpeg", "data": part["image_url"].split(",", 1)[1]}}
                    for part in item["content"]
                ]})
        return contents

    def usage(self, payload):
        usage = payload.get("usageMetadata") or {}
        output = usage.get("candidatesTokenCount")
        return {"model": payload.get("modelVersion"), "usage": {
            "input_tokens": usage.get("promptTokenCount"),
            "input_tokens_details": {"cached_tokens": usage.get("cachedContentTokenCount", 0) if usage else None},
            "output_tokens": output + (usage.get("thoughtsTokenCount") or 0) if isinstance(output, int) else None,
        }}
