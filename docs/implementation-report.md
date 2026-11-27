# Historical ShotCoach implementation report

This report records the earlier Gemini-era implementation and evaluation. See the [current coaching guide](coaching.md) for the OpenAI runtime and evaluation commands.

## What was delivered

The current `main` working tree includes an evidence-based coaching flow in the existing FastAPI and Streamlit app. Players can ask about selected recordings, compare two saved shots, see real frames near shooting events, and receive a physical cue and a targeted exercise. The app can remember the focus, accept a practice report, compare later recordings, and adapt the recommendation. Esin’s form-profile computation remains the source of personal makes-versus-misses associations.

The backend used staged Gemini tool retrieval and structured decisions. The server checked measurement eligibility, shot ownership and evidence IDs before putting observations into the answer. It also checked model-selected visual movement against the corresponding pose samples. The design kept personal claims reproducible and gave a deterministic answer when Gemini was unavailable.

## Files changed

| Area | Files |
|---|---|
| Coaching engine | `backend/app/agent/coaching_agent.py`, `context.py`, `evidence.py`, `knowledge.py`, `memory.py`, `player_input.py`, `profile.py`, `progress.py`, `response.py`, `retrieval.py`, `video.py` |
| HTTP | `backend/app/api/main.py`, `backend/app/api/coaching.py` |
| Interface | `frontend/app.py`, `frontend/coaching.py` |
| Tests | `tests/test_coaching.py`, `tests/test_coaching_frontend.py` |
| Evaluation code | `evaluation/fixtures.py`, `run.py`, `scenarios.py`, `smoke.py` |
| Evaluation artifacts | `evaluation/baseline.json`, `baseline-main.json`, `results.json`, `smoke-results.json` |
| Documentation | `README.md`, `docs/coaching.md`, `docs/implementation-report.md` |

## Verified results

| Check | Result |
|---|---|
| Full pytest suite | **71 passed** on Python 3.11 with the host’s incompatible pytest asyncio plugin disabled and Windows loopback available. |
| Deterministic coaching evaluation | **22 of 22 checks passed**. The artifacts include the input question, available evidence, expected behaviour, claims to avoid, actionability criteria and the actual application result. |
| Streamlit AppTest | Submitted a coaching question, rendered actual frame images and timestamps, opened playback, and verified that switching players cleared chat and the selected shot. |
| Local HTTP smoke | FastAPI and Streamlit both started on loopback. The demo returned readable estimated-release and early follow-through JPEGs, refused a frame request scoped to another player, and stored an explicitly reported practice completion. |
| Saved frame check | `free_throw_03` decoded preparation at frame 28 (0.933 s), estimated release at frame 76 (2.533 s), and early follow-through at frame 82 (2.733 s). |
| Baseline replay | The original revision loaded and recorded that the Gemini key was unavailable. |
| Diff and syntax | `git diff --check` and Python bytecode compilation passed. |

[Deterministic evaluation outputs](../evaluation/results.json) · [Local HTTP smoke output](../evaluation/smoke-results.json)

### Baseline and final sample outputs

The baseline records contain ten prompts, follow-up ordering, selected shot IDs, model settings and available tool snapshots. The earlier working branch baseline is `62d095f`. The resumed implementation uses the `991adcb` baseline from `main`. Both captures recorded zero live requests because `GEMINI_API_KEY` was unavailable. [Earlier baseline](../evaluation/baseline.json) · [Main baseline](../evaluation/baseline-main.json)

Examples from the final deterministic coach on the same demo:

- **What should I practice today?** The coach suggested setting the feet, choosing a spot on the rim and keeping the same comfortable rhythm throughout a short set from one spot.
- **Can you show me what I should change?** The response identified the clip moments available for review and provided real frame references.
- **I tried your previous advice, but it did not help.** The coach recalled the assigned exercise, set its cue aside and asked what felt different.

The evaluation artifact includes the exact output for each baseline prompt. It separately captures a mocked numeric-only run with zero attached images, a mocked visual run with two images, a run with prior turns, and rejection and repair of an invalid frame reference. These exercise the contract and preserve its outputs. Original-versus-final quality, visual-versus-numeric quality and conversation-aware usefulness still need live model responses and human review.

The weighted rubric uses grounding (25%), decision quality (20%), actionability (15%), clarity (15%), personalization (10%), visual relevance (10%) and continuity (5%). Rate each applicable criterion from 0 to 4. Divide the weighted result by the sum of applicable weights and report that denominator. The rubric records fabricated measurements, invalid video references, isolation failures, unsafe medical advice and unsupported definitive causal claims separately as critical failures. No subjective scores were assigned in this run.

## Follow-up Gemini verification

A Gemini key became available after the original baseline and final evaluation artifacts were saved. Synthetic-only requests exposed an HTTP 400 schema rejection. The coach now sends the Pydantic decision through the SDK’s JSON Schema field. A request intercepted at the HTTP transport verifies the wire payload and strict local validation. If the optional tool-selection request fails, the coach proceeds with the evidence it already collected. An automated test exercises that recovery path.

Live synthetic requests using the corrected schema returned HTTP 503. The coach produced grounded fallback feedback from the synthetic fixture. The earlier tool-selection probe returned HTTP 504. The automatic approval review rejected the bundled-demo run because it would disclose selected recording frames and coaching context to Google without explicit approval for those materials.

## Open verification and limits

- **Gemini.** Live multimodal and baseline/final verification remain pending. They depend on provider availability and approval to send the selected demo footage and coaching context. The schema, model requests, repair path and grounded application output passed deterministic tests.
- **Fresh upload.** The existing pipeline requires `ROBOFLOW_API_KEY` for remote hoop detection. This run verified coaching from the stored demo video and exercised the existing vision component tests. A fresh complete upload with Roboflow was not run.
- **Visual and progress scope.** The pipeline supplies estimated events and may have no confirmed landing. Corroborated image movement is limited to supported elbow and knee frame pairs. Progress matches recorded shot type and arm. Distance, fatigue, recording order and camera conditions may differ.
- **Deployment.** The app uses local player profiles selected by name. The coaching tools and media routes validate shot ownership within that scope. A shared deployment would need authenticated player identity throughout the app.

The working tree contains no commits or deployment changes from this implementation.

## Run the app and checks

Install the dependencies in the project virtual environment and configure the service keys in `.env` when available. Start the services in separate terminals from the project root.

```powershell
python -m pip install -r backend/requirements.txt
python -m uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8000
```

```powershell
python -m streamlit run frontend/app.py --server.address=127.0.0.1
```

Open Streamlit, select `TestPlayer`, load `free_throw_03` and ask to see the follow-through. Use **My practice plan** to record feedback and **Compare two recordings** for an explicit pair.

```powershell
python -m pytest -p no:asyncio
python -m evaluation.run --live
python -m evaluation.smoke
```

The evaluation commands use isolated copies of the demo database. The optional live comparison requests one demo question in three configurations. Use `--output` to preserve previous result files. The original Gemini captures remain linked above.
