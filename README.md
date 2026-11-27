# AI Basketball ShotCoach

An AI basketball coach that analyses free-throw videos. Computer vision measures the player's shooting form and the ball's flight. ShotCoach stores the results per player and uses the configured coaching provider to answer questions with those measurements, the player's history and curated coaching knowledge. OpenAI is the default.

## How it works

```
Streamlit UI (frontend/app.py)
   │  HTTP
   ▼
FastAPI backend (backend/app/api/main.py)
   ├─ Upload a video ─► pipeline (backend/app/pipeline/video_pipeline.py)
   │     0. Video preparation                  ─► MOV / iPhone video converted to H.264 MP4
   │     1. Pose estimation (MediaPipe)        ─► joint angles and wrist positions
   │     2. Shot segmentation                  ─► knee dip and a first release estimate
   │     3. Ball detection (YOLO)              ─► ball candidates in every frame
   │     4. Hoop detection (Roboflow)          ─► rim position on one frame,
   │        + hoop tracking (local)            ─► then followed through every frame
   │     5. Ball tracking                      ─► the path of this shot's ball,
   │        + release correction               ─► release = ball leaves the hands
   │     6. Biomechanics                       ─► knee / elbow features
   │     7. Shot outcome                       ─► made / missed / unknown
   │     8. Combined analysis                  ─► outputs/<video_id>/shot_analysis.json
   │     9. Save to SQLite                     ─► data/shotcoach.db
   │
   ├─ Several shots (separate clips) ─► background job with progress
   │     Find shots with MediaPipe, cut clips and run the one-shot pipeline on each.
   ├─ Upload a practice video with several shots
   │     ─► background job (backend/app/pipeline/multi_shot_pipeline.py)
   │        convert to 30 fps / 1080p ─► find every shot (ball reaching the hoop)
   │        ─► cut one clip per shot ─► steps 0–9 for each clip,
   │           all shots saved in one practice session
   │
   ├─ Full recording with session coaching ─► scan the continuous recording
   │     Combine pose and ball motion to measure attempts at their original timestamps.
   │
   └─ Ask the coach ─► Coaching engine (backend/app/agent/coaching_agent.py)
         tools: shot analysis, player history, shot comparison,
                curated coaching knowledge and drills (backend/app/agent/knowledge.py),
                personal form profile (backend/app/ml/form_profile.py)
```

The personal form profile compares each player's own made and missed shots, so feedback is based on what works for that player rather than on one ideal form for everyone.

## Setup

Requires Python 3.13. Run all commands from the project root.

1. Create and activate a virtual environment:

   ```bash
   python -m venv .venv
   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1
   # Windows (Git Bash)
   source .venv/Scripts/activate
   # macOS / Linux
   source .venv/bin/activate
   ```

2. Install the dependencies (about 2–3 GB, mostly PyTorch):

   ```bash
   python -m pip install -r backend/requirements.txt
   ```

3. Create your `.env` file from the template and add your own keys:

   ```bash
   cp .env.example .env
   ```

   | Key | Used for | Where to get it |
   |---|---|---|
   | `OPENAI_API_KEY` | The coaching agent | [OpenAI API keys](https://platform.openai.com/api-keys) |
   | `ROBOFLOW_API_KEY` | Hoop detection when uploading a video | [Roboflow](https://roboflow.com) workspace settings |

   The coach defaults to OpenAI with `gpt-4.1-mini`. Set `SHOTCOACH_PROVIDER=gemini` and `GEMINI_API_KEY` to use Gemini. Set `SHOTCOACH_MODEL` to select the model for the active provider. The provider-specific `OPENAI_MODEL` and `GEMINI_MODEL` also work when `SHOTCOACH_MODEL` is unset. The local fallback is available when the selected provider has no key.

   Never commit `.env`; it is listed in `.gitignore`.

## Running the app

Start the backend and the frontend in two separate terminals, both from the project root with the virtual environment activated.

```bash
# Terminal 1: FastAPI backend on http://127.0.0.1:8000
python -m uvicorn backend.app.api.main:app --host 127.0.0.1 --port 8000

# Terminal 2: Streamlit frontend on http://localhost:8501
python -m streamlit run frontend/app.py
```

Then open http://localhost:8501. To check the backend on its own, open http://127.0.0.1:8000/api/health.

## Recording tips

- Upload **one free throw**, or a **practice video with several free throws** (choose "Several shots" in the app). In a practice video every shot is found automatically (each time the ball reaches the hoop, including shots taken straight after each other), cut into its own clip and analysed. This takes several minutes for a long video.
- Choose the matching option: a video with several shots uploaded as "One shot", or a video with one shot uploaded as "Several shots", is refused with a message.
- Only one video is analysed at a time; uploads are refused until the current analysis has finished.
- Film from the **side**, with the player's **whole body and the hoop** in the picture for the whole shot.
- A **steady camera** (tripod or a fixed stand) gives the most reliable results. A handheld camera is supported, but sudden zooms can make the made/missed result `unknown`.
- **Record continuously: do not pause the recording between shots, and do not zoom.** The app cuts out each shot itself, so waiting time costs nothing. If the video jumps during a shot (recording paused and resumed, cut, or zoomed), the release is often missing: the shot is still saved with its made/missed result, but its angles are shown as **Not measured** instead of wrong values.
- MP4 and MOV (including iPhone HEVC) are accepted, up to 1 GB. MOV and unreadable MP4 videos are converted to H.264 MP4 automatically.
- Select the **shooting arm** before analysing.

## Made, missed and unknown

The shot outcome is decided from the ball's path and the rim position in 2D:

- **made**: the ball comes down close to the rim centre and is briefly hidden by the rim and net.
- **missed**: the ball comes down clearly beside the rim.
- **unknown**: the app is not sure, for example when the ball falls just in front of the rim, which looks like a make from the side.

The app prefers `unknown` over a wrong guess. Set the result yourself with the ✅ Made / ❌ Missed buttons; a manual label always overrides the automatic one. The personal form profile only uses shots labelled made or missed.

## Running the tests

```bash
python -m pytest
```

## Project structure

| Path | Contents |
|---|---|
| `backend/app/api/` | FastAPI endpoints |
| `backend/app/pipeline/` | Video preparation (MOV conversion) and all analysis steps for an uploaded video |
| `backend/app/computer_vision/` | MediaPipe pose estimation |
| `backend/app/shot_detection/` | Shot segmentation, release correction and their evaluation |
| `backend/app/measurements/` | Joint angles and shot features |
| `backend/app/ball_detection/` | Ball detection and tracking, hoop detection and tracking, shot outcome |
| `backend/app/analysis/` | Combined shot analysis and shot comparison |
| `backend/app/database/` | SQLite models, saving shots, player history |
| `backend/app/agent/` | Shared coaching engine, provider adapters and evidence tools |
| `backend/app/ml/` | Personal form profile (form-to-outcome model, stage 1) |
| `tests/` | Automated tests |
| `frontend/` | Streamlit user interface |
| `.streamlit/` | Streamlit settings (upload size limit) |
| `sample_videos/` | Sample free-throw videos shared with the team |
| `outputs/` | Analysis results per video |
| `data/` | SQLite databases and uploaded videos (see below) |

## Data: what is shared and what stays on your machine

| Shared through git | Stays on your machine (ignored by git) |
|---|---|
| `sample_videos/` | Uploaded videos (`data/uploads/`) |
| Demo outputs: `outputs/free_throw_01..03`, `outputs/shot_b8a4046d9f91`, `outputs/shot_55ce5ca18a50` | Outputs of any new upload (`outputs/shot_*`) |
| `data/seed_shotcoach.db`: the demo shots for player `TestPlayer` | Your live database, `data/shotcoach.db` |

On first run, if `data/shotcoach.db` does not exist, the app creates it by copying the seed database. After that, your uploads only go into your own live database. To reset to the demo data, stop the backend, delete `data/shotcoach.db` and start it again.

To share real recorded data with the team, use a private shared folder for the videos instead of git.

## Privacy

- **Roboflow:** for each analysed shot, **one frame** is sent to Roboflow's hosted model to find the hoop (a practice video sends one more frame to find its shots, so a video with 20 shots sends 21 frames). Everything else (pose, ball, hoop tracking) runs on your computer.
- **Gemini:** when you ask the coach a question, the question and the player's measurements, history and form profile are sent to Google's Gemini API.
- **Uploaded videos** are stored on your computer in `data/uploads/` and are not deleted automatically. They are never committed to git.
- Only record and upload other people with their **consent**, and upload each player under their own name.

## Current limitations

- Practice videos: one player and one ball at a time, with the hoop in the picture. Shots are found from the ball reaching the hoop; this found every shot in two test videos (22 of 22 and 21 of 21), but has only been tested on these two. A shot that never comes near the rim (an airball) is not found. If no hoop is found, the app falls back to finding shots by the hands going above the head, which can miss shots when the player is small in the picture. The progress of a running practice video is lost if the backend restarts.
- Shot outcome is a 2D heuristic: balls falling just in front of or behind the rim are reported as `unknown`. The made rule was checked on 27 real shots (no wrong results, 11 `unknown`); more varied recordings are needed to confirm it.
- The release frame comes from the ball leaving the hands and is accurate to about one frame (33 ms at 30 fps); without a visible ball the pose-only estimate is used.
- The elbow angle at release is only accurate to about ±25°: the elbow straightens by about 30° per frame at release, so one frame earlier or later changes it a lot. The knee angle is much more stable. All angles are 2D estimates from the side view and have not been compared with a reference measurement.
- Shots where the video jumps during the shot are marked Not measured; shots analysed before this check keep their stored values unless they are corrected or analysed again.
- Shots analysed before an analysis improvement keep their stored results until they are analysed again.
- The personalised form-to-outcome model is at stage 1 (comparing makes and misses per feature); it needs at least 10 labelled shots, with at least 3 made and 3 missed.
- The curated coaching knowledge focuses on shooting technique and practice.
- Joint angles are 2D and depend on camera position; a side view works best.
