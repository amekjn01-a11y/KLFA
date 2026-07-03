# KLFA Score Manager

FastAPI + SQLite based tournament score manager.

## Files

- `score_web_app.py`: Web app
- `score_manager_app.py`: Desktop app that reads the same `score_web.db`
- `requirements_web.txt`: Python dependencies
- `start_score_web.bat`: Windows local start script
- `Procfile`: Generic web process command
- `render.yaml`: Render deployment configuration

## Local Run

```bash
python -m pip install -r requirements_web.txt
python -m uvicorn score_web_app:app --host 0.0.0.0 --port 8000
```

Open `http://127.0.0.1:8000/`.

## Render Deployment

1. Push this repository to GitHub.
2. In Render, create a new Blueprint or Web Service from the GitHub repository.
3. Use these settings if entering them manually:
   - Build Command: `pip install -r requirements_web.txt`
   - Start Command: `python -m uvicorn score_web_app:app --host 0.0.0.0 --port $PORT`
   - Health Check Path: `/healthz`
   - Environment Variable: `DATA_DIR=/var/data`
4. Add a persistent disk mounted at `/var/data` so `score_web.db` is not lost after redeploys.

## Data

The live score data is stored in `score_web.db`.

Do not commit `score_web.db`, CSV files, or backup files to GitHub. They may contain real tournament data. Copy `score_web.db` to the server data folder separately when moving existing data to production.
