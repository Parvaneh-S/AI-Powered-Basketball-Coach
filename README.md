# AI Basketball ShotCoach

An agentic AI basketball coach that analyses free-throw videos. Computer vision measures the player's shooting form and the ball's flight, the results are stored per player, and a Gemini-based agent answers coaching questions using those measurements, the player's history and retrieved coaching knowledge.

## How it works

```
Streamlit UI (frontend/app.py)
   │  HTTP
   ▼
FastAPI backend (backend/app/api/main.py)
   ├─ Upload a video ─► pipeline (backend/app/pipeline/video_pipeline.py)
   │     1. Pose estimation (MediaPipe)        ─► joint angles
   │     2. Shot segmentation                  ─► start / release / end frames
   │     3. Ball detection (YOLO)              ─► ball positions
   │     4. Ball tracking                      ─► ball trajectory
   │     5. Hoop detection (Roboflow)          ─► rim position
   │     6. Biomechanics                       ─► knee / elbow features
   │     7. Shot outcome                       ─► made / missed / unknown
   │     8. Combined analysis                  ─► outputs/<video_id>/shot_analysis.json
   │     9. Save to SQLite                     ─► data/shotcoach.db
   │
   └─ Ask the coach ─► Gemini agent (backend/app/agent/coaching_agent.py)
         tools: shot analysis, player history, shot comparison,
                coaching knowledge (RAG, backend/app/rag/knowledge_retriever.py)
```

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
   | `GEMINI_API_KEY` | The coaching agent | [Google AI Studio](https://aistudio.google.com) |
   | `ROBOFLOW_API_KEY` | Hoop detection when uploading a video | [Roboflow](https://roboflow.com) workspace settings |

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

## Project structure

| Path | Contents |
|---|---|
| `backend/app/api/` | FastAPI endpoints |
| `backend/app/pipeline/` | Runs all analysis steps for an uploaded video |
| `backend/app/computer_vision/` | MediaPipe pose estimation |
| `backend/app/shot_detection/` | Shot segmentation and its evaluation |
| `backend/app/measurements/` | Joint angles and shot features |
| `backend/app/ball_detection/` | Ball detection and tracking, hoop detection, shot outcome |
| `backend/app/analysis/` | Combined shot analysis and shot comparison |
| `backend/app/database/` | SQLite models, saving shots, player history |
| `backend/app/agent/` | Gemini coaching agent and its tools |
| `backend/app/rag/` | Coaching knowledge base and semantic search |
| `frontend/` | Streamlit user interface |
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

## Current limitations

- Each uploaded video is analysed as a single shot.
- Shot outcome detection is experimental and often returns `unknown` when the ball is hidden near the rim.
- The personalised form-to-outcome model from the proposal is not implemented yet.
- The coaching knowledge base has only 4 entries.
- Joint angles are 2D and depend on camera position; a side view works best.
