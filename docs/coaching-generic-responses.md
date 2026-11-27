# Investigation of generic coaching responses

This report records the original investigation and provider results. The reproduction command at the end uses the current OpenAI implementation.

## What produced the quoted answer

All the quoted phrases exist in the shooting-arm entry of [the coaching knowledge base](../backend/app/agent/knowledge.py). The hand position is its cue, “Close one-hand form shots” is its drill title, and the instruction to compare the clips was its evaluation copy. The Jr. NBA link is a source for general drill information.

Before the fix, FastAPI passed the question and recording or session selection to the coach. The coach assembled scoped evidence, including available personal patterns, verified frame references and retrieved knowledge. Gemini received that evidence in its structured request. Its response schema supplied identifiers, an intent and other selections. The renderer pulled the rationale, cue and instructions from the knowledge entry regardless of whether Gemini or fallback chose the topic. Validation checked the selected IDs and available evidence. Streamlit rendered the response fields it received, with the purpose in a caption when one was supplied. The legacy plain-text API answer omitted the explanation and evaluation.

The original request log and exact question were unavailable. A synthetic one-shot reproduction asking “What should I practice for my shooting arm?” produced the quoted cue, title, instructions, comparison sentence and source through both deterministic fallback and a mocked Gemini decision. The wording therefore cannot identify which path handled the original turn. [Captured before responses](../evaluation/coaching-generic-before.json)

## Changes

Gemini can now author the rationale, cue, practice instructions and evaluation plan. It receives the relevant principles and applicability from the knowledge base. The server continues to render personal observations, measurements, outcomes, frame labels and source links from typed, player-scoped evidence. A personal adjustment must cite a validated association in the same coaching topic. An available applicable pattern is used when proposing an adjustment. Without that evidence, the response identifies the drill as general guidance.

The server rejects unsupported IDs, numeric claims, certain unverified observations and unsafe or invalid draft shapes. A separate model review checks the proposed wording against the cited evidence and coaching purpose. Validation failures get a bounded repair attempt. If a draft cannot be approved, the deterministic coach still connects supported observations to a concrete movement experiment and a next-recording check. The review adds an error-checking layer for natural language. Personal factual claims remain under the existing evidence contract.

When matching representative frames exist, ShotCoach retrieves the relevant phases and compares them. The response tells the player which part of the movement to look at and how it differs in the selected examples. Missing frames are disclosed. Streamlit renders the explanation in the main answer and keeps **Supporting coaching sources** expandable. The Jr. NBA link remains a supporting source.

Set `SHOTCOACH_DEBUG=1` for an opt-in server-side development trace. It records retrieved evidence and supporting knowledge, the original structured model output, validation errors, repair or fallback, the selected focus and the final rendered result. API credentials are redacted. The trace omits the prompt’s conversation history and image data. Coaching evidence and generated text can contain player information, so leave the flag off on shared deployments.

## Before and after

On the same single-shot fixture, the old answer ended by telling the player to compare their own clips. The new answer labels the drill “General practice option” and says, “Record another set from the same spot and angle. I’ll review the movement across attempts and track makes separately when outcomes are available.”

On different synthetic datasets with the same question, the coach instead made opposite, evidence-backed suggestions:

- **Straighter elbow on makes.** “Try a slightly straighter shooting arm as the ball leaves your hand.”
- **More bent elbow on makes.** “Try a slightly softer bend in your shooting arm as the ball leaves your hand.”

Both responses reported the pattern as an association and proposed filming a comparable set so ShotCoach could check the release movement and outcomes separately. The approved mocked draft described an empty-hand rehearsal before shooting and how the coach would align the release frames.

Two live Gemini attempts used fictional measurements and text only. The requests returned HTTP 504 and 503, respectively. The app returned grounded fallback coaching on both attempts. Live authored responses remain unverified. All 104 automated tests and the local FastAPI and Streamlit smoke check passed. The tests cover the authored path, review, repair, rejection, development trace and Streamlit display. [After responses and live error traces](../evaluation/coaching-generic-after.json)

Run `python -m evaluation.coaching_generic` to reproduce the deterministic and mocked output. Add `--live` to make a bounded live request with the fictional fixture. Run `python -m pytest -p no:asyncio` in the current Windows environment.
