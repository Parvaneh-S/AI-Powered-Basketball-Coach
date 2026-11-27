# ShotCoach GPT-6.1 Terra live evaluation

November 26, 2026 · `free_throw_01.mp4` · attempt 1

GPT-6.1 Terra completed all four questions in one conversation, with one validator repair and no evaluation retry. It gave a more coherent, evidence-led assessment of the knee motion, attached the relevant visuals, and delivered a verified instructional video. Its prose still omitted the two reliable shot-level angle values, and its practice guidance repeated across turns. The total estimated API charge was **$0.0315584** against the **$0.25** limit. The baseline came from the previous live run. [Saved GPT-4.1 mini report](live-openai-single-shot.md) · [Terra trace](live-openai-terra.json)

## Access and compatibility

- The configured API key returned HTTP 200 from the model-list endpoint and listed `gpt-6.1-terra`. All nine generation requests completed under that model and returned the Standard service tier.
- The production Responses adapter sent `store: false`, `max_output_tokens: 4096`, `include: ["reasoning.encrypted_content"]`, and the existing non-strict JSON schema. On tool-enabled requests it sent the existing non-strict function definitions and `parallel_tool_calls: false`. It omitted temperature. The run exercised `retrieve_shot`, `retrieve_frames`, and `retrieve_knowledge`, including function outputs, JPEG data URLs with `detail: "auto"`, encrypted reasoning replay, and JSON parsing and repair. The remaining published functions used the same schema transport and were available to the model throughout tool-enabled requests.
- An evaluation-only request override set `reasoning.effort: "medium"` and `service_tier: "default"`. The API confirmed medium with `all_turns` context, standard reasoning mode and no reasoning summary. Terra supports `none`, `low`, `medium` (default), `high`, `xhigh` and `max`. The production adapter has no explicit effort setting and can use Terra’s documented medium default. [GPT-6.1 Terra model reference](https://developers.openai.com/api/docs/models/gpt-6.1-terra) · [Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
- Standard short-context USD rates per million tokens were **$1.00 input, $0.05 cache reads, $1.25 30-minute cache writes and $5.00 output**, including reasoning. The 12-hour cache write rate is $2.50 and this run reported zero tokens at that lifetime. Before each generation, the guard priced the exact input token count at the cache-write rate, added 256 input tokens of headroom and reserved the full output cap. It settled the reservation against returned usage before the next request. All nine preflight input counts matched billed input counts. [Model pricing](https://developers.openai.com/api/docs/models/gpt-6.1-terra) · [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) · [Input token counting](https://developers.openai.com/api/docs/guides/token-counting)

## Evidence and comparison

The run read the saved single-shot fixture and carried the preceding player-facing text into each turn. It used empty memory, with persistence disabled. The current coaching selector consumed saved pose and video data. No new computer vision analysis ran. The single-shot scope leaves live multi-session personalization outside this evaluation.

**Outcome-source fixture error.** I reused the existing replay test fixture, which copied the archived display value `player label` into the raw `RecordedShot.outcome_source` field. Production expects `manual` there and translated the fixture value to `experimental detector` in the model’s shot evidence. The saved annotation is a manual miss, as reported by the baseline. Terra repeated the evidence it received on turn 1, so that sentence is inaccurate for the clip and the two runs cannot be compared on outcome-source handling. A local check with `manual` recovered `player label` in the evidence and returned the same measurements and corrected release/follow-through frames. [Saved annotation](../outputs/free_throw_01/shot_annotations.json) · [Replay fixture](../tests/test_single_shot_coaching.py) · [Outcome display mapping](../backend/app/agent/evidence.py)

| Criterion | GPT-6.1 Terra on the current coach | Saved GPT-4.1 mini run |
|---|---|---|
| Coaching judgment | Prioritized the clearest available movement, the knee dip and rise. Withheld elbow judgment and a form change, treated the comfortable dip as provisional, and proposed filming a comparable set before judging repeatability. | Acknowledged poor elbow coverage but shifted to unverified arm extension and repeatedly used the single miss to motivate routine changes. |
| Measured evidence | Cited the verified knee range on turns 1–3 and the shot on turns 1 and 4. Neither the 88.82° minimum nor the 74.61° range appeared in the player-facing prose. Knee coverage was 100% over 30 frames. Elbow coverage was 69.44%, below the 80% gate. | Zero structured supporting evidence IDs and neither reliable knee angle in the final prose. |
| Visual accuracy | Chose frames 38 and 49 for right-knee bend and extension. The images support the description. Turn 2 explained that the arrow represents movement in the image and does not measure force. | Turn 1 included the same frame under two labels. Turn 2 had zero attachments and described a lowered arm at frame 110 as extended forward. |
| Instructional resource | Chose a verified Jr. NBA two-hand form shooting video for the knee bend and rise, and told the player what to watch. The free-throw-specific alternative was also retrieved and focused on pre-shot rhythm. The chosen video had a relevant movement focus, though it was a less direct match to the shot type. | Named the free-throw video, returned no verified card, and told the player no verified video was found. |
| Natural conversation | Stayed on the same movement through all four turns. Turn 2 answered the visual request directly and turn 4 answered what to keep. Three turns repeated the comfort and repeatability check in similar language. | Carried themes forward but repeatedly offered another drill, including after direct questions. |
| Actionable guidance | Gave camera setup, a clear movement to compare and a way to track outcomes separately. The resource card added a same-spot exercise. The advice had no explicit rep count, set count or time target. | Turn 3 supplied a concrete two-set, ten-rep routine. Its routine change was less grounded in what this clip measured. |

**What the offline engineering accounts for.** The current app explicitly surfaces the reliable knee observations, deduplicates same-frame phase selections, bounds early follow-through to frame 55 (six frames after estimated release), supplies frames for explicit visual requests when needed, and refreshes eligible video results from the specific search topic. Existing offline replay tests exercise the saved mini drafts against these fixes and show that a correct frame attachment and verified video card are possible with the old model output. The fixtures also exercise guardrails for unsupported habits and resources. [Single-shot regression tests](../tests/test_single_shot_coaching.py)

**What Terra contributed.** The raw drafts show Terra chose to call for the knee pair, specified the direction of comparison in the frame request, selected the knee range as evidence, phrased the coaching as a provisional judgment, and used the prior discussion to search for knee bend and rise. It chose the movement-matched card from two eligible resources and articulated what to watch. These are observed authoring decisions. The simultaneous changes to evidence and validation, the outcome-source fixture error, and the single clip prevent a controlled model-only comparison.

The coaching improvement is meaningful for this clip, especially in the visual explanation and the decision to wait for more attempts before prescribing a change. Live performance on longitudinal or poorly measured clips remains open. This run alone is insufficient evidence for a permanent model switch.

## Visuals, retrieval and validation

| Turn | Player-facing attachments | Retrieval and validation |
|---|---|---|
| 1 | [Knee dip, frame 38 at 1.267 s](live-openai-terra-frames/turn-1-knee_dip-38-knee.jpg) (89.9° overlay) and [knee extension, frame 49 at 1.633 s](live-openai-terra-frames/turn-1-knee_extension-49-knee.jpg) (163.4° overlay, image-plane arrow). | Retrieved the selected shot and knee frames. The validator interpreted “One attempt” as an ambiguous numeric claim, so the built-in repair rephrased it to “This clip.” |
| 2 | [Knee dip, frame 38](live-openai-terra-frames/turn-2-knee_dip-38-knee.jpg) and [knee extension, frame 49](live-openai-terra-frames/turn-2-knee_extension-49-knee.jpg). Same two JPEGs as turn 1. | Retrieved the same knee phase pair explicitly. Accepted on first draft. |
| 3 | A verified Jr. NBA video card, including watch-for, relevance and exercise text. | The video search `shooting leg motion knee dip and rise` returned the `knees` and `arm` principles, and the two verified videos below. The validator stripped the generic opening sentence “I recommend this form-shooting video” under its unverified-recommendation rule. It retained the eligible card and the remaining prose. No repair request. |
| 4 | None. | No active tool lookup. Accepted on first draft. |

Turn 1’s initial principles were `mechanics`, `arm`, `finish`, `individual`, `routine`, `recording` and `knee_dip_depth`. Turn 2 and turn 4 received `routine` and `recording`. Turn 3 initially received `recording` and `routine`, then cited `knees` after its lookup. The individual overlay values above are frame measurements with different sources. The shot-level minimum and range come from the saved feature summary.

- **Selected:** `jrnba_two_hand_form`, Dale Ellis’s *Form Shooting-2 Hands*. The card directs the player to the guide hand and extension through the finish. Terra’s prose focuses the viewing on knee bend and rise. [Jr. NBA publisher page](https://jr.nba.com/video/form-shooting-2-hands/)
- **Also retrieved:** `jrnba_free_throw`, Megan Griffith’s *Fundamentals of the Free Throw*. The catalog focus was the pre-shot sequence and repeatable rhythm. [Jr. NBA publisher page](https://jr.nba.com/video/fundamentals-of-the-free-throw/)

The baseline recorded narrative repairs on turns 1 and 2. Its pre-repair drafts contained elbow-angle claims and the `arm_straightens` tag. The saved baseline trace does not retain the original validator messages for those repairs. Turn 3 discarded the unoffered resource ID and an adaptation without an active objective. Turn 4 discarded a proposed practice that included shooting during a no-release rehearsal and an adaptation without an active objective.

## Tokens, latency and cost

Output includes reasoning tokens. API time covers generation requests. Wall time also includes input-count preflights and local coaching. The preflights took **4.191 s** in total. Costs use the provider-reported cache-write, cache-read and output counts. The conservative settled upper bound was **$0.0315654**.

| Turn | Calls | Input | Cache read | Cache write | Output | Reasoning | API time | Wall time | Estimated USD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 4 | 19,574 | 7,803 | 11,759 | 767 | 159 | 15.278 s | 18.616 s | $0.0189359 |
| 2 | 2 | 7,988 | 5,152 | 2,830 | 278 | 0 | 6.228 s | 7.193 s | $0.0051911 |
| 3 | 2 | 7,712 | 5,312 | 2,394 | 196 | 0 | 5.636 s | 6.295 s | $0.0042441 |
| 4 | 1 | 3,589 | 1,936 | 1,650 | 205 | 46 | 3.453 s | 4.154 s | $0.0031873 |
| Terra total | 9 | 38,863 | 20,203 | 18,633 | 1,446 | 205 | 30.594 s | 36.258 s | $0.0315584 |
| Saved mini total | 9 | 43,931 | 3,584 | 0 | 1,661 | 0 | 24.846 s | 26.576 s | $0.0191548 |

Terra cost about 1.24 cents more and took 5.75 s more in API time. Its wall time was about 9.68 s longer, including the preflights. Architecture, prompt size, caching and request scheduling can also affect the timing and cost deltas.

| Call | Purpose | Input | Cache read | Cache write | Output | Reasoning | JPEGs | API time | Preflight | Estimated USD |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.1 | Plan shot lookup | 3,416 | 0 | 3,413 | 53 | 24 | 0 | 2.655 s | 0.885 s | $0.00453425 |
| 1.2 | Plan frame lookup | 4,393 | 3,413 | 977 | 50 | 0 | 0 | 1.707 s | 0.299 s | $0.00164490 |
| 1.3 | Generate | 5,943 | 4,390 | 1,550 | 337 | 68 | 2 | 5.758 s | 0.604 s | $0.00384500 |
| 1.4 | Repair | 5,822 | 0 | 5,819 | 327 | 67 | 2 | 5.157 s | 0.405 s | $0.00891175 |
| 2.1 | Plan frame lookup | 3,219 | 1,936 | 1,280 | 50 | 0 | 0 | 1.698 s | 0.388 s | $0.00194980 |
| 2.2 | Generate | 4,769 | 3,216 | 1,550 | 228 | 0 | 2 | 4.529 s | 0.337 s | $0.00324130 |
| 3.1 | Plan video lookup | 3,379 | 1,936 | 1,440 | 31 | 0 | 0 | 1.892 s | 0.263 s | $0.00205480 |
| 3.2 | Generate | 4,333 | 3,376 | 954 | 165 | 0 | 0 | 3.744 s | 0.342 s | $0.00218930 |
| 4.1 | Generate | 3,589 | 1,936 | 1,650 | 205 | 46 | 0 | 3.453 s | 0.670 s | $0.00318730 |

## Regression status

The full Windows suite passed **344 tests in 131.45 s**, including the Streamlit playground integration and the single-shot and longitudinal coaching tests. The run used `python -m pytest -p no:asyncio -q tests --tb=short -o faulthandler_timeout=75` with localhost available and live provider credentials disabled. Plain pytest hit 20 collection errors because the installed `pytest-asyncio` plugin expected a removed fixture-manager attribute. The documented plugin override allowed the full suite to run. No product regression blocked this evaluation. The fixture source mapping and the lack of live multi-session coverage remain limits on interpreting it.

## Complete player-facing responses

The following quotes preserve the returned text. The turn table links each image.

### 1. Analyze my shooting form. What should I improve?

> Your clearest starting point is your **leg motion**: in this free throw, you bend your knee and straighten it as you rise toward release. That’s worth keeping if it feels comfortable; the clip doesn’t show that you need a deeper or shallower dip.
>
> I wouldn’t prescribe a form change yet. The elbow measurements aren’t reliable enough to judge your arm, and the recorded miss comes from an experimental detector rather than a confirmed result. This clip also can’t tell us what you repeat.
>
> **Next step:** Record a set of free throws from a steady angle, with your whole body in view. Check whether your dip and rise feel comfortable and look similar across attempts, and record the results yourself. That will give us a better basis for choosing what to improve.

### 2. Can you visually show me what you mean?

> Look at your right knee in the highlighted frames:
>
> - **Knee dip:** Your knee is bent as you load for the shot.
> - **Rise toward release:** Your knee is much straighter as you rise. The arrow shows its movement across the image, not the force of the movement.
>
> That bend-and-straighten motion is what I meant by your leg motion. If it feels comfortable, there’s no reason from this clip alone to change how deep you dip. In a recorded set, check whether the motion looks similar and feels comfortable across attempts.

### 3. Can you recommend a specific instructional video and explain what I should focus on?

> **Watch the player’s knee bend and rise** as the ball moves toward the release—not to copy the exact depth, but to see how the legs extend through the shot.
>
> In your clip, your knee bends and then straightens as you rise. If that feels comfortable, keep it for now. On your next recorded set of free throws, check whether your dip and rise feel comfortable and look similar across attempts.
>
> Form Shooting-2 Hands · Jr. NBA
> https://jr.nba.com/video/form-shooting-2-hands/
>
> Watch how the guide hand supports the ball and how the legs and shooting arm extend through the finish.
>
> Use this example alongside your measured knee angle change across the shot.
>
> Take a short set at the same spot and repeat the same comfortable bend. Compare how similar the bend looks across the set and record makes separately.

### 4. Is there anything about my current technique that I should keep rather than change?

> Yes—**keep your knee bend and rise**, provided they feel comfortable. In the free throw we reviewed, your knee bent as you loaded and straightened as you rose toward release. There’s no evidence in that clip that you need to change the depth of your dip.
>
> Keep it as your starting point, then check a comparable set of free throws to see whether that motion feels comfortable and looks similar across attempts. The single clip can’t tell us how consistently you repeat it.
