# How ShotCoach works

## Coaching flow

Streamlit sends a question, the selected shot, an optional explicit comparison and up to ten recent role-marked turns to FastAPI. The backend scopes evidence to the selected player and starts one conversation with the configured provider. The model can request more evidence through read-only tools, whose results stay in the conversation used for the answer. The response contains conversational text and may include references, frames or a practice proposal. The backend verifies and resolves those references before returning the existing Streamlit response shape.

The existing upload and analysis pipeline still handles pose tracking, shot segmentation, trajectory, hoop detection, outcomes and SQLite storage. Upload invokes the pipeline on demand, so the coaching and analysis routes can open existing recordings without loading the vision models at server startup.

## Session coaching

Selecting a recording opens its parent practice session. The coach can use that session’s evidence and automatically show representative attempts where a measured makes-versus-misses pattern supports them. A recording can contain one or several numbered shots. Session accuracy uses known outcomes, and outcome coverage is shown separately. See the [session coaching implementation report](session-coaching.md).

## Measurements and evidence

The machine-readable [measurement dictionary](../backend/app/agent/evidence.py) defines fields, units, calculation, shooting phase, reliability indicators, supported interpretations and unsupported interpretations. It includes start-to-release duration, knee and elbow measurements, and pose and ball tracking coverage. Duration uses the stored pipeline value. The elbow angle at estimated release is the angle of the shoulder–elbow–wrist joint in the image. Ball launch angle, release speed, force and power would require separate evidence.

Evidence carries a player, session, shot and recording identifier, provenance, measurements and samples where the pipeline recorded counts. The measurement status is `valid`, `unreliable` or `missing`. A usable estimate still depends on the camera view, landmark detection and event estimates. Tracking coverage reports the share of frames with readings. The coach excludes unusable values and distinguishes manual outcomes, experimental estimates and unknown outcomes. Cohorts and comparisons expose their sample counts and available shooting conditions.

## Coaching tools

| Coaching tool | What it can retrieve |
|---|---|
| `retrieve_shot` | An owned shot from a recording or shot ID, or the active selection |
| `retrieve_history` | Recent owned recordings and outcome counts, with an optional outcome filter |
| `retrieve_comparison` | An explicitly identified pair in the requested order, with reliable measurement differences |
| `retrieve_make_miss` | A shot of the opposite recorded outcome, matched by shot type and shooting arm, with the same session preferred |
| `retrieve_profile` | Conditions, associations, sample counts and supporting shots from the existing form-profile analysis |
| `retrieve_frames` | Selected phases from an owned recording, focused pose overlays, or equivalent phases across two owned attempts |
| `retrieve_knowledge` | Curated principles by topic or scoped coaching context, with optional verified videos and readings |
| `retrieve_memory` | Player-stated goals and experience, the recent objective and reports |
| `retrieve_progress` | Baseline and subsequent counts and movement spread for the active objective |
| `retrieve_session` and `retrieve_attempts` | Outcome coverage, measurement distributions and paginated attempts for the selected session |
| `retrieve_historical_profile` | Form-profile results from other owned sessions |
| `retrieve_representative_comparison` | Decoded matching-phase examples for a selected current association |

The [form-profile adapter](../backend/app/agent/profile.py) delegates to Esin’s `compute_form_profile` and follows its existing feature eligibility and statistical methods. It filters unreliable measurements, groups by the selected shot's recorded conditions when available, and includes contributing shot IDs, association direction, sample sizes, interval and caveats. The original form-profile code remains intact. If imports fail, the coaching adapter returns an unavailable state.

## Video and model providers

A video reference ties a decoded frame and source timestamp to an owned attempt and estimated phase. The coach chooses phases for the question. Elbow placement can use preparation and estimated release. Knee movement can use the deepest measured bend and the straightest measured position between that bend and release. Follow-through can use estimated release and the stored early post-release frame. Landing requires a confirmed event.

The frame tool accepts an optional overlay focus of `elbow`, `knee` or `alignment`. It can retrieve matching phases for a second attempt in one call. For a sequence in one attempt, the tool can mark image-plane displacement from an earlier phase when both samples contain the joint. Camera motion can affect the displacement. The existing pose pass saves visible normalized landmarks in `pose_landmarks.json` beside the angle CSV. OpenCV draws the requested marks on the resized JPEG, using the saved per-frame angle where all three landmarks agree with it. If a legacy pose replay gives different geometry, the overlay uses the angle measured from those landmarks and labels its source. The browser scales the JPEG and the marks together.

Coaching cards show the attempt, phase and source timestamp. Matching phases appear side by side on desktop and stack on narrow screens. Playback seeks to the original fractional timestamp. Technique comparisons work with unknown outcomes. A direct make-versus-miss visual comparison uses player-entered labels.

New analyses save coordinates automatically. Older recordings with original video and a saved angle CSV can still show clean frames and the available measurements. The shared demos include landmark files backfilled with the existing pose model. To backfill a clip, run `python -m backend.app.computer_vision.pose_estimator free_throw_03.mp4 --landmarks-only` with its stored filename from `sample_videos` or `data/uploads`. This preserves the saved analysis and footage. If some joints are missing, the overlay draws only the joints it has. Archives that have only a pre-annotated video can still serve the existing plain frame reference.

OpenAI is the default provider and uses `gpt-4.1-mini`. Gemini can be selected with `SHOTCOACH_PROVIDER=gemini`, `GEMINI_API_KEY`, and optionally `SHOTCOACH_MODEL`. Both adapters use the same coaching instructions, evidence and tools. Each answer can use up to five tool rounds, with up to four independent lookups per round, and one local-validation repair that fixes only the flagged problems. `OPENAI_MODEL=gpt-6.1-terra` selects the stronger reasoning model and `SHOTCOACH_REASONING_EFFORT` optionally sets its effort. Tool results enter the same request history as the answer. Image-enabled conversations attach up to four verified JPEG frames. Numeric-only requests retain verified references for the interface. A visual movement tag needs two decodable images from one shot and agreement with the corresponding pose samples. Supported tags cover elbow movement from estimated release to early follow-through and knee movement from preparation to estimated release.

## Knowledge and response validation

Phase 5.1 expanded the catalog from 17 to 105 knowledge entries and from eight to 34 instructional resources (28 videos and six readings). The original catalog offered broad shooting cues and drills. The expansion adds specific topics for joint coordination, release and spin, shot types, footwork and timing, skill progression, fatigue, movement comfort, and what to review when a cue fails. Each new entry records the coaching principle, applicable situations, limitations, a practical application and a source. The agent uses evidence labels to distinguish observational studies, research reviews, coaching guidance, clinical guidance and hypotheses to test.

The 88 new entries cite 37 source pages. The catalog pairs biomechanics and skill-learning research with specific Jr. NBA and USA Basketball guidance. Limits include small or specialized study samples, camera-dependent mechanics, and weak evidence for attributing an individual miss to a particular joint. Unconventional mechanics are evaluated against comfort, repeatability and the player's goal. [Release and distance study](https://pmc.ncbi.nlm.nih.gov/articles/PMC8256521/) · [Elbow and wrist coordination study](https://pubmed.ncbi.nlm.nih.gov/20552519/) · [Fatigue review](https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2025.1435810/full) · [Motor-learning review](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2024.1377122/full)

Phrase matching ranks detailed entries, while qualified measurements, a stated goal, experience and practice feedback can supply a related entry for personal coaching. The knowledge tool returns up to two principles. In the mocked spin-axis example, the first request’s dynamic context was 3,032 UTF-8 bytes, including 1,137 bytes of knowledge. The tool output was 1,517 bytes. These figures exclude the shared system instruction, tool schema and provider request envelope.

### Instructional resources

The original catalog tied topic keywords to coaching principles and app-authored drills. It could filter drills for available equipment and feedback, but a phrase such as “my shot feels rushed” was hard to match and many source links were shared across unrelated topics.

The local lookup now gives specific phrases more weight than overlapping words. It can use the question, qualified observations, repeatability patterns, stated goals and existing practice feedback to prioritize principles. Known effectiveness and comfortable individual movement remain valid reasons to keep an existing technique. The model receives relevant principles separately from footage and player measurements.

An explicit request can surface up to two options in the first provider request. The coach can also call `retrieve_knowledge` with `resource_kind` set to `video`, `article` or `any`. The response can select one offered ID. ShotCoach resolves the exact metadata locally and connects the resource to a cited matching measurement or phase frame when available. The card offers a practice application when it fits the player’s stated constraints and existing feedback. The lookup uses recent conversation turns to avoid repeating links.

The checked-in [resource catalog](../backend/app/agent/resources.py) stores metadata reviewed on November 26, 2026. Publisher video pages have watch cues and applicable skill levels, and selected readings have named sections. Video timestamps are omitted where exact offsets were unavailable. If a narrowly matched topic has no verified resource, the coach can still use the principle. Offline tests check duplicate URLs, valid publisher paths and catalog references. Link discovery and playback availability checks are manual. [Form Shooting-2 Hands](https://jr.nba.com/video/form-shooting-2-hands/) · [Fundamentals of the Free Throw](https://jr.nba.com/video/fundamentals-of-the-free-throw/) · [BEEF - Acronym for Shooting Form](https://www.usab.com/videos/2021/04/beef-acronym-for-shooting-form) · [The Basic Jump shot](https://www.usab.com/news/2023/05/the-basic-jump-shot)

### Coaching principles and response checks

The [foundational principles](../backend/app/agent/knowledge.py) include cues, progressions and evaluation targets where applicable. The [expanded library](../backend/app/agent/knowledge_library.py) adds narrower explanations and applications. Drill wording and set suggestions are ShotCoach practice designs derived from these sources. The recording guide follows the existing camera-dependent pose pipeline. [USA Basketball shooting mechanics](https://www.usab.com/news/2014/01/7-tips-to-improve-your-shooting-mechanics) · [Jr. NBA practice drills](https://jr.nba.com/jrnbaathome/) · [NBA rules](https://official.nba.com/rule-no-5-scoring-and-timing/) · [NHS shoulder pain guidance](https://www.nhs.uk/symptoms/shoulder-pain/)

The earlier knowledge index covered balanced feet and a comfortable knee bend, a repeatable free-throw routine, guiding the ball with the shooting arm, and a relaxed wrist and follow-through. The current catalog covers these topics. [Earlier Jr. NBA shooting guide](https://jr.nba.com/shooting/) · [Earlier Jr. NBA shooting FAQ](https://jr.nba.com/faq/shooting/)

The selected model interprets the question, selects which evidence matters and authors the message. References, practice cards and objective updates are optional. The server checks references, verifies numeric measurements, distinguishes prospective practice doses, guards known unsupported or unsafe claims and validates changes to memory. The pipeline uses local validation and a bounded repair. If either cannot produce a safe answer, or the provider fails, the coach uses the evidence-based fallback. Explicit recording comparisons apply the requested pair's scope. Pain requests use a conservative response that pauses the aggravating movement and recommends qualified assessment where appropriate.

The response schema is in [response.py](../backend/app/agent/response.py). The existing API's `answer` string is accompanied by a `coaching` object for Streamlit. The object includes a message, optional observations, strengths, evidence IDs, frames with timestamps, cue, exercise and evaluation target, uncertainty, sources, clarification, previous focus, progress and an acknowledgement of a saved coaching decision.

## Memory and progress

### Reviewing more than one session

The original coach stored player goals and preferences, a practice objective with a baseline, and reports about that objective. It also offered a pooled form profile and matching-phase frame comparisons. Without a saved objective, its progress path had no baseline. Repeated continuation decisions appended copies of the same plan, and contradictory feedback could remain active.

The coach can now compare up to three compatible sessions without an active objective, or use the original baseline when reviewing an adjustment. It selects owned sessions in saved order and matches recorded shot type and shooting arm. Accuracy and movement consistency are reported independently. Directional accuracy comparisons use at least eight player-confirmed outcomes and 80% confirmed coverage per endpoint, with a ten-percentage-point descriptive threshold. Movement comparisons use at least five valid measurements and 75% measurement coverage, for the same metric and phase. The spread thresholds are two degrees or 30 milliseconds. These are conservative reporting rules for the recorded samples. Opposing changes across measures or sessions are surfaced as mixed results.

Camera angle and distance are generally absent from old recordings. The coach can honor a reported camera change or distance mismatch in the comparison request. Even where direction can be described, projected angles and sample differences cannot establish lasting improvement or the effect of an adjustment. The matched-phase image tool can show representative frames, and an instructional resource can accompany the comparison when useful. The historical profile can retrieve associations that recur across earlier sessions or show opposing directions. This recurrence review uses player-confirmed outcomes and stays separate from the existing pooled profile.

### Reviewing and correcting practice history

A new recommendation records the exact instructions, dose and evaluation as a coaching proposal. Continuation and discontinuation update the existing objective. A changed drill or a progression keeps the original plan available for review. Feedback records completion, difficulty and the player’s own assessment separately. Repeating the same report leaves the previous entry in place, and a corrected assessment replaces its earlier version. For example, “Actually, I’m intermediate,” “Clear my saved goal,” and “Actually, I didn’t complete the drill” update the corresponding saved information. An explicitly temporary constraint such as “Today I have no hoop” applies to the coaching turn.

For a drill that did not help, the coach can retrieve the instructions, the player report and a relevant newer comparison before asking what happened or selecting a different exercise. With a helpful and completed exercise, a request for more challenge can add one repetition per set when the dose still fits the player’s constraints. This follows the player’s report, and subsequent recordings still measure effectiveness and repeatability separately.

The first provider request includes at most one relevant plan and three linked reports. The memory tool can retrieve a specific owned recommendation on demand. Session review packets include compact sample summaries and up to three frame candidates per endpoint. The frontend presents the comparison in the existing coaching reply and retains the original exercise in its previous-focus details.

The conversation stays in the current Streamlit session, with a ten-message and 6,500-character backend prompt budget. Selecting a different shot keeps the conversation. Switching player profiles clears the current selection and conversation.

Persistent context uses the `coaching_memory` table in the existing SQLite database. It keeps the player’s stated goals, experience and feedback preferences alongside practice recommendations and progress. Choose a player and a recording to get started. The coach chooses a practice focus from the available evidence and conversation. Goals, experience and feedback preferences can be shared in chat. When the coach recommends a focus, **My practice plan** offers completion and feedback controls. Players can also report completion or failed advice in chat. Progress is measured from recorded baseline shots and subsequent database entries that match the known conditions. An upload alone carries no claim about completing an exercise. A reset clears coaching context and rotates its revision so an in-flight answer cannot restore it.

When a player reports that the current drill felt difficult, the coach can simplify the exercise for that focus. A chat report can trigger an adjustment in the same reply. A report saved in **My practice plan** informs the next relevant request for an exercise. The adjusted plan keeps its easier prescription for that focus. Recorded shooting outcomes and form measurements continue to determine the progress comparison.

The raw spread is available from two usable measurements. The stronger coverage and sample rules above govern directional summaries. Practice decisions can continue, modify, advance or discontinue an objective.

## Running and evaluating

### Offline replay of the live single-shot evaluation

The [original report](../evaluation/live-openai-single-shot.md) and [captured requests, responses and tool results](../evaluation/live-openai-single-shot.json) record the original four-turn run. `tests/test_single_shot_coaching.py` uses the original provider drafts and tool calls with the production coaching path and saved footage. The replay makes no provider requests and cannot predict what a model would newly write in response to the revised instructions.

| Finding | Cause and fix |
|---|---|
| Reliable knee evidence was overlooked | The model received it alongside lower-quality evidence without an explicit lead. Its first draft used 88.8°, but the repair dropped that measurement after validation rejected the phrasing. The selected-attempt packet now highlights valid, in-scope movement measurements. The shared instructions treat them as observations to explain, with no coaching fault inferred from an angle alone. |
| The visual follow-up displayed no frames | The model's repaired draft omitted frame IDs and the app only rendered frames explicitly attached to the response. Explicit visual requests now attach eligible distinct frames even when the draft omits IDs. Coaching de-duplicates frame aliases before presentation. |
| The follow-through frame showed the player walking | The evaluation fixture supplied the full attempt end as `end_frame`. Production coaching retrieval also treated that field as the early frame. The lookup now uses saved timestamps within six frames and 250 ms of estimated release. In the archived clip this changes frame 110 to frame 55. The validator rejects the captured claim that the late frame shows forward arm extension. |
| The resource lookup missed an available video | The first lookup missed the generic request with its trailing explanation clause. The explicit media tool then reused the empty shortlist. It now looks up the tool's topic, including routine terminology, and still respects modality, narrow topic matching and opt-outs. The response resolves offered catalog titles to cards and removes unverified recommendations from prose. |
| The reply generalized from a single miss | The shared instructions limit claims to the selected attempt and ask for a concrete next check. The captured claim about an established arm habit now fails validation. A single-shot fallback can describe the measured knee bend and condition any suggestion to preserve it on the player's comfort. |

The first archived repair flagged the optional arm movement tag, the rounded 88.8° knee measurement and a 131° shot-level elbow claim. The second flagged the 52° and 131° frame angles. The validator now drops an unsupported tag independently, accepts clearly identified rounded measurements and checks scoped overlay angles against images actually sent. Unreliable shot-level elbow measurements and unsupported descriptions of follow-through still fail validation. When the archived visual repair repeats the unsupported claim, the replay falls back to a qualified explanation and keeps the attached frames.

The playground's existing **Debug** panel includes `provenance.request_usage` with per-request stages, token counts and latency, plus the interaction total. The same data appears in development traces when `SHOTCOACH_DEBUG=1`. Set `SHOTCOACH_MODEL_PRICING` to a JSON map of model IDs to `input`, `cached_input` and `output` rates in USD per million tokens. The legacy `SHOTCOACH_OPENAI_PRICING` variable still works. The estimate uses the returned model's rates first and then the requested model's rates. Missing usage or pricing is shown as null, and the interaction total is null if any request cannot be priced.

Follow the [project setup](../README.md#setup) and run FastAPI plus Streamlit. With the OpenAI key unset, the demo recordings at `TestPlayer` exercise coaching, history and playback locally. Configuring `OPENAI_API_KEY` enables live model selection and visual interpretation. Configuring `ROBOFLOW_API_KEY` enables remote hoop detection during a fresh upload. Local form analysis still runs when hoop evidence is unavailable. Both services are designed for a trusted loopback installation. Player names select local profiles. Network exposure would require a real authentication and authorization boundary for the legacy and coaching routes.

Use `python -m pytest` in the project virtual environment. On a host with the incompatible preinstalled pytest asyncio plugin, run `python -m pytest -p no:asyncio`. Run `python -m evaluation.run` for local comparisons and `python -m evaluation.smoke` to verify both local servers. Use `python -m evaluation.coaching_generic --live --output coaching-probe.json` for a live check with fictional measurements and no images. The optional `evaluation.run --live` comparison sends selected demo frames and context to the configured provider. See the [implementation report](implementation-report.md) for results and reproducibility details.
