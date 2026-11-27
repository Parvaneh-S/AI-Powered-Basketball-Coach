# ShotCoach live single-shot evaluation

November 26, 2026 · `gpt-4.1-mini-2025-04-14`

The four requested questions ran in one conversation on bundled demo clip `free_throw_01.mp4`, attempt 1. The existing saved manual annotation labels the shot a **miss**. The evaluation used the production coach, OpenAI adapter, frame tools and response validators. Each turn received the preceding player-facing text and the same one-shot snapshot. The run used empty coaching memory in an isolated database with persistence disabled.

**Result.** The coach carried forward its earlier advice and produced an actionable routine exercise. It underused the reliable knee measurements, dropped visual attachments from the visual follow-up, and contradicted itself about whether it had found a verified video. One confirmed miss cannot establish the player's usual accuracy or consistency.

## Saved evidence and scope

- Right-knee minimum **88.82°** and range **74.61°**, with **100%** knee coverage across 30 frames. Both passed the per-measurement gate. These are camera-plane measurements.
- The saved shot was marked for review. Elbow coverage was **69.44%**, below the **80%** gate. Shot-level elbow and timing metrics were withheld from the model as unreliable. Individual frame overlays still displayed saved elbow angles where landmarks were available.
- Saved preparation began at frame **20** and estimated release was frame **49**. The evaluation populated the shot's end from the saved manual annotation at frame **110**. That field is normally used by coaching frame selection as an early follow-through reference. Here it exposed an end-of-attempt frame roughly **2.03 s** after release, and the visible player is walking with the arm lowered. This fixture choice limits the follow-through assessment. The remaining visual and resource findings do not depend on that frame.
- The same owned shot record, outcome count and current profile were supplied on all four turns. The profile had a sample of one. No computer vision analysis was rerun. Multi-shot comparisons and multi-session progress evaluation are **deferred**.

## Evaluation findings

| Criterion | Finding |
|---|---|
| Measured evidence | Partial. Turn 1 observed knee loading and acknowledged the unreliable elbow metrics. It omitted the reliable knee measurements from both its explanation and evidence citations. All four answers returned zero structured supporting evidence IDs. |
| Natural, actionable coaching | Partial. Turn 3 supplied a concrete two-set routine and a comfort/repeatability check. The responses repeatedly offered another drill and used broad setup and finish advice. |
| Annotated frame retrieval and display | Partial. The model retrieved three elbow overlays on each of turns 1 and 2. Turn 1 attached all three, including two identical frame-49 images under different phase labels. The isolated frame API and Streamlit replay rendered all three images and timestamp controls. Turn 2 attached none even though its prose described the images. It also described the late frame as a forward arm extension, which the saved frame does not show. |
| Expanded knowledge | Partial. The initial packet included `knee_dip_depth`, a Phase 5.1 entry relevant to the valid measurements. The coach did not cite or visibly apply it. The only active knowledge lookup returned the existing `routine` and `arm` entries. |
| Verified instructional resource | Failed this turn. The model named the relevant Jr. NBA title, but the tool returned no eligible resource and the validator removed the unoffered ID. The player got no resource card and also saw a message saying no verified video was found. The title and topic were independently confirmed on the publisher page. [Fundamentals of the Free Throw, Megan Griffith, Jr. NBA](https://jr.nba.com/video/fundamentals-of-the-free-throw/) |
| Conversation continuity | Partial. Turn 2 continued the elbow discussion and turn 4 retained the same extension, knee loading and routine themes. It also carried the weak arm inference forward. |
| Claims about accuracy, consistency and misses | Partial. The coach did not give a personal make rate or explicitly identify the cause of the miss. It repeatedly used this single miss to motivate a routine change and characterized the arm and knee mechanics as habits worth keeping. One attempt does not support either pattern-level claim. |

## Complete player-facing responses

The text below is the saved player-facing response text for each turn. Additional captions, media and response fields are in the [full JSON trace](live-openai-single-shot.json).

### 1. Analyze my shooting form. What should I improve?

> Reviewing your shooting form from the available frames, your knee bend at the deepest dip shows a clear loading phase, and your elbow is bent at release, indicating you are guiding the ball with your shooting arm. However, the exact elbow angles and extension after release are not reliably measured here, so I cannot confirm the degree of arm extension or changes through follow-through.
>
> Since this shot was missed, focusing on a consistent and comfortable shooting routine could help. You might try rehearsing a steady setup and a smooth follow-through to build repeatability. This approach aligns with general shooting mechanics principles emphasizing balance, coordinated lift, and a comfortable finish.
>
> If you'd like, I can suggest a simple practice drill to work on these aspects. Would you be interested?

Initial knowledge offered includes `mechanics`, `arm`, `finish`, `individual`, `routine`, `recording`, `knee_dip_depth`. The reply cited `mechanics`, `arm`, `finish`, `routine`.

| Retrieved phase | Frame | Video time | Right elbow overlay | Attached |
|---|---:|---:|---|---|
| knee dip | [38](live-openai-single-shot-frames/turn-1-knee_dip-38.jpg) | 1.267 s | 52° | Yes |
| knee extension | [49](live-openai-single-shot-frames/turn-1-knee_extension-49.jpg) | 1.633 s | 131.2° | Yes |
| release | [49](live-openai-single-shot-frames/turn-1-release-49.jpg) | 1.633 s | 131.2° | Yes |

### 2. Can you visually show me what you mean?

> Looking at the images from your shot, at the knee dip phase your elbow is bent, showing you are preparing to push the ball upwards. By the release phase, your elbow is more extended, indicating you are straightening your arm to release the ball. The follow-through frame shows your arm is extended forward, but the exact elbow angle there is not measured.
>
> This sequence shows a typical arm extension through the shot, which is good for guiding the ball. Since this shot was missed, one thing to check is the consistency of your elbow extension and follow-through across multiple shots. A smooth, repeatable extension and a comfortable follow-through often help improve accuracy.
>
> Would you like to compare this with a made shot or try a drill to build a consistent shooting routine?

Initial knowledge offered includes `routine`, `recording`. The reply cited no catalog entries.

| Retrieved phase | Frame | Video time | Right elbow overlay | Attached |
|---|---:|---:|---|---|
| knee dip | [38](live-openai-single-shot-frames/turn-2-knee_dip-38.jpg) | 1.267 s | 52° | No |
| release | [49](live-openai-single-shot-frames/turn-2-release-49.jpg) | 1.633 s | 131.2° | No |
| follow through | [110](live-openai-single-shot-frames/turn-2-follow_through-110.jpg) | 3.667 s | Landmark marker only | No |

### 3. Can you recommend a specific instructional video and explain what I should focus on?

> I recommend the Jr. NBA video on shooting consistency titled "Fundamentals of the Free Throw." It focuses on developing one repeatable routine to give you a clear starting point for practice. The key points to focus on are setting your feet, picking a spot on the rim, and using the same comfortable rhythm each time. This helps give each attempt a similar setup, which is crucial for building accuracy and confidence.
>
> Since your current shot shows a typical arm extension but was missed, working on a consistent routine can improve your repeatability and comfort. You can practice by repeating your free-throw routine with attention to a steady setup and smooth follow-through.
>
> Would you like me to suggest a simple drill to practice this routine?
>
> I couldn’t find a verified video for this request in the coaching catalog.
>
> Set your feet the same way each time, pick a target spot on the rim, and shoot with a comfortable rhythm. Focus on repeating the same setup and follow-through for each shot.
>
> Check if your shots feel more consistent and comfortable, and if your make rate improves over a small set of attempts.
>
> Prescribed practice target: 2 set(s) of 10 repetitions; allow 600 seconds including resets.

Initial knowledge offered includes `recording`, `routine`. The reply cited `routine`.

The tool query was `shooting routine` with resource kind `video`. It returned `routine` and `arm` with resource status `no_match`. No resource card or new frame was attached.

### 4. Is there anything about my current technique that I should keep rather than change?

> Your current shooting technique shows a typical arm extension pattern through the shot, which is a good habit to keep as it helps guide the ball. The knee bend at the dip phase also indicates a solid loading movement. These elements provide a foundation for a consistent shot.
>
> Since your shot was missed, the main area to focus on is building a repeatable and comfortable shooting routine rather than changing your arm or knee mechanics. Keeping your arm extension and knee bend as they are, try to develop a steady setup and smooth follow-through that you can repeat every time. This consistency often leads to better accuracy.
>
> Would you like me to suggest a simple drill to practice this consistent routine?

Initial knowledge offered includes `routine`, `recording`. The reply cited `routine`.

This turn issued no tool calls. The validator removed the proposed practice and unsupported adaptation.

## Usage and latency

The single evaluation completed without provider errors or a rerun. Two turns used the production validator's internal repair. The budget guard checked the request before sending it and accounted for returned usage. Wall-clock coaching latency totaled **26.576 s** across all turns, including **24.846 s** of provider requests. Offline frontend replay is excluded.

| Turn | Calls | Input | Cached input | Output | Wall time | Estimated USD |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 3 | 16,513 | 0 | 654 | 10.714 s | $0.0076516 |
| 2 | 3 | 15,598 | 0 | 452 | 8.042 s | $0.0069624 |
| 3 | 2 | 7,867 | 3,584 | 313 | 4.760 s | $0.0025724 |
| 4 | 1 | 3,953 | 0 | 242 | 3.061 s | $0.0019684 |
| Total | 9 | 43,931 | 3,584 | 1,661 | 26.576 s | $0.0191548 |

Rates were $0.40 per million standard input tokens, $0.10 per million cached input tokens, and $1.60 per million output tokens. [OpenAI GPT-4.1 mini pricing](https://developers.openai.com/api/docs/models/gpt-4.1-mini)

| Turn / call | Stage | Input | Cached input | Output | API time | Estimated USD |
|---|---|---:|---:|---:|---:|---:|
| 1.1 | planning | 3,702 | 0 | 45 | 2.401 s | $0.0015528 |
| 1.2 | generation | 6,327 | 0 | 375 | 4.491 s | $0.0031308 |
| 1.3 | repair | 6,484 | 0 | 234 | 3.171 s | $0.0029680 |
| 2.1 | planning | 3,483 | 0 | 42 | 1.344 s | $0.0014604 |
| 2.2 | generation | 6,095 | 0 | 249 | 3.405 s | $0.0028364 |
| 2.3 | repair | 6,020 | 0 | 161 | 2.504 s | $0.0026656 |
| 3.1 | planning | 3,678 | 0 | 23 | 1.428 s | $0.0015080 |
| 3.2 | generation | 4,189 | 3,584 | 290 | 3.087 s | $0.0010644 |
| 4.1 | generation | 3,953 | 0 | 242 | 3.015 s | $0.0019684 |
