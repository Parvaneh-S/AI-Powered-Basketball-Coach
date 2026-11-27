# Session-based ShotCoach implementation

## Starting point

The prior pipeline already produced whole-recording pose angles, visible wrist coordinates and ball detections. It selected one knee dip and estimated release, followed one ball path, scored one rim crossing and saved one shot in a practice session. The database already associated shots with players and sessions, and the coach could compare manually selected shot IDs. The missing pieces were repeated event segmentation, independent shot windows, explicit recording storage, a collective analysis and automatic visual examples.

## Recording pipeline and data

An upload now creates a recording with its existing video ID and one parent practice session. The recording and its shots save in one SQLite transaction. The new `recordings` table keeps source metadata, a per-player duplicate fingerprint, and processing diagnostics. Each detected attempt has a numbered shot ID, its own measurement snapshot and outcome, and the parent recording and session IDs. Legacy singly stored shots are still visible through the recording and session routes.

The revised detector looks for local elbow extension cues on the selected shooting side and checks for a tracked ball leaving a visible wrist and continuing upward. Multiple cues around one estimated release are consolidated. Isolated motions and incomplete evidence are logged for review. Attempt windows retain source frame numbers and timestamps. The existing angle extraction runs on only the attempt’s preparation through early follow-through. The outcome analyzer receives its own post-release ball trajectory, clipped before the next preparation and after a bounded flight interval. Missing or ambiguous rim evidence yields unknown outcomes. The combined preview overlays only the ball paths selected for individual attempts.

## Session coaching

The player chooses an uploaded or saved recording. A concise summary shows detected attempts, known-outcome accuracy, outcome coverage and usable form coverage. Attempt measurements and manual outcome labels are expandable. The coach can answer session questions with the recording selected and show two representative attempts automatically. In-session examples share phases and carry the numbered shot, recorded outcome, timestamp and an optional playback segment. Optional manual comparison is still available.

Session summaries include outcome denominators, manual and estimated labels, per-metric sample sizes, spread and earlier/later descriptive differences when ordering comes from one recording under matching known conditions. Esin’s original `compute_form_profile` supplies statistical associations and sample eligibility through the existing adapter. The app uses the selected session’s cohort for current advice and makes a separate historical profile available. Recording order supplies no evidence of fatigue or causation.

The coaching evidence layer provides tools for a session summary, a paginated outcome-filtered attempt list, historical form patterns and the prepared representative comparison. Existing tools still supply shot details, current form patterns, knowledge, past recommendations, practice reports and progress. The context sends aggregates and bounded evidence. Frame selection sends at most four actual images.

For a supported association, the selector ranks relevant measurements and finds examples near the made and missed group medians. It checks that the examples agree with the direction of the association and that the relevant phase frames actually decode. Equally representative cases prefer manual outcomes. Each image is attached to the observation it illustrates. Sessions with one outcome group, insufficient samples or unavailable images can still receive a useful summary and practice cue.

A practice focus assigned from a session records that session as the baseline. Follow-up uses a selected newer session when available, or the latest eligible session by default. Progress compares known-outcome accuracy and the selected form measurement separately, includes the sample sizes and uses the existing form-profile adapter to compare detected associations. Recorded shot type and shooting arm determine basic comparability. The app can use a player's practice feedback when deciding whether to continue or change a cue.

## Example responses

- **Mixed-outcome fixture, knee-bend pattern.** The coach identifies that the knee at its deepest bend looked more bent on makes in the fixture and reports the sample sizes. It selects a representative made attempt and missed attempt, then suggests testing a comfortable repeatable knee bend in one short set.
- **No confirmed outcomes, real-footage check.** The coach can report the detected attempts and unknown outcomes, then use the available form measurements for guidance. A made-versus-missed visual comparison requires known outcomes and a supported association.
- **Missed-shot question.** When the detector has evidence of lateral misses, the coach reports how often tracked flight passed beside the rim. It can propose recording another set from the same spot without asserting what caused the misses.

## Verification

The full suite passed **98 tests**. The synthetic 20-attempt fixture exercised mixed outcomes, window isolation, distinct shot IDs and absolute timestamps. Other tests covered duplicate and incomplete cues, unknown outcomes, insufficient and poor-tracking sessions, frame ownership, representative median selection, session progress, API ownership, the Streamlit workflow and legacy single-shot coaching.

A separate full local run concatenated three copies of the bundled real `free_throw_03` clip. Fresh MediaPipe and YOLO inference processed 579 frames. The pipeline saved three attempts in SQLite. Estimated release occurred at frames 78, 271 and 464 (2.600 s, 9.033 s and 15.467 s). All three had usable form measurements. The run generated both browser previews and kept all three outcomes unknown because hoop detection was disabled. [Fresh inference results](../evaluation/session-video-fresh.json)

A separate replay reused the sample’s saved ball detections, reran pose inference, reproduced the three release frames, decoded all three JPEGs from the stitched recording and exercised the session coach. The recorded answer was “I detected 3 attempts. The outcomes are unknown. The usable form data does not point to a clear change.” [Replay output and session summary](../evaluation/session-video-replay.json)

Run the isolated verification using `python -m evaluation.session_video`. Use `--input` for a local continuous recording or `--saved-demo-detections` to reuse the bundled demonstration’s saved ball detections while running fresh pose inference. Run the tests with `python -m pytest -p no:asyncio` when the host’s incompatible pytest plugin is installed.

## Remaining limits

The real exercise used repeated clips from one original recording. Accuracy on naturally continuous, varied practice footage, live Gemini generation and live Roboflow hoop detection were outside the verified run. Very short, obscured or unconventional attempts may lack enough linked pose and ball evidence to separate cleanly. The segmentation and outcome rules remain experimental. Known matching conditions currently cover shot type and shooting arm. Longer recordings take more CPU time and the interface reports elapsed processing time while the upload completes.
