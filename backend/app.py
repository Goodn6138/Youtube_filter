# backend/app.py
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from transformers import pipeline
import uuid
import time

# -------------------------
# Load model (once)
# -------------------------
# This can be heavy on first import. Make sure your server has enough RAM.
classifier = pipeline("zero-shot-classification", model="facebook/bart-large-mnli")

# -------------------------
# App + CORS
# -------------------------
app = FastAPI(title="AI Shorts Filter - Classification + User Preferences")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this in production to your extension domain
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------------------------
# In-memory storage (simple)
# -------------------------
# prefs_by_client: client_id -> {"prefs": [...], "updated_at": timestamp}
prefs_by_client: Dict[str, Dict[str, Any]] = {}

# analytics: list of events (very simple logger)
analytics_log: List[Dict[str, Any]] = []

# default candidate labels used when user doesn't provide preferences
DEFAULT_LABELS = ["educational", "entertainment", "music", "sports", "news", "comedy"]

# -------------------------
# Pydantic models
# -------------------------
class Video(BaseModel):
    title: str
    description: Optional[str] = ""
    # Optionally pass wanted labels directly in the classify request
    wanted_labels: Optional[List[str]] = None
    # Optional client id to fetch stored prefs
    client_id: Optional[str] = None

class Prefs(BaseModel):
    client_id: Optional[str] = None   # server will create one if missing
    wanted_labels: List[str]

# -------------------------
# Helpers
# -------------------------
def now_ts() -> float:
    return time.time()

def log_event(event: Dict[str, Any]):
    event["ts"] = now_ts()
    analytics_log.append(event)

# -------------------------
# Endpoints
# -------------------------

@app.post("/prefs", summary="Create or update user preferences (wanted content labels).")
def set_prefs(p: Prefs):
    """
    Save user preferences. If client_id is not provided, server will generate one and return it.
    The client should store the returned client_id (e.g. in chrome.storage) and include it in future classify requests.
    """
    client_id = p.client_id or str(uuid.uuid4())
    prefs_by_client[client_id] = {
        "wanted_labels": [lab.strip().lower() for lab in p.wanted_labels if lab.strip()],
        "updated_at": now_ts(),
    }
    log_event({"event": "set_prefs", "client_id": client_id, "prefs": prefs_by_client[client_id]["wanted_labels"]})
    return {"client_id": client_id, "wanted_labels": prefs_by_client[client_id]["wanted_labels"]}

@app.get("/prefs/{client_id}", summary="Get saved preferences for a client_id.")
def get_prefs(client_id: str):
    prefs = prefs_by_client.get(client_id)
    if not prefs:
        raise HTTPException(status_code=404, detail="client_id not found")
    return {"client_id": client_id, "wanted_labels": prefs["wanted_labels"], "updated_at": prefs["updated_at"]}

@app.post("/classify", summary="Classify a video and decide if it matches user preferences.")
def classify(video: Video, request: Request):
    """
    Classification behavior:
    - If `video.wanted_labels` is provided in the request, use them as candidate labels.
    - Else, if `video.client_id` provided and server has saved prefs, use them.
    - Else, fall back to DEFAULT_LABELS.
    The endpoint returns:
      - allowed: True/False (does top_label match one of the wanted labels?)
      - top_label, confidence, all_scores
    """
    # choose candidate labels
    wanted = None
    if video.wanted_labels and len(video.wanted_labels) > 0:
        wanted = [w.strip().lower() for w in video.wanted_labels if w.strip()]
    elif video.client_id:
        prefs = prefs_by_client.get(video.client_id)
        if prefs and prefs.get("wanted_labels"):
            wanted = prefs["wanted_labels"]

    # if no user-specified labels, use default labels
    candidate_labels = wanted if wanted and len(wanted) > 0 else DEFAULT_LABELS

    text = (video.title or "").strip() + ". " + (video.description or "").strip()
    if not text.strip():
        raise HTTPException(status_code=400, detail="Empty title and description")

    # Perform zero-shot classification
    result = classifier(text, candidate_labels=candidate_labels)
    # result has 'labels' and 'scores'. labels[0] is the top label.
    top_label = result["labels"][0].lower()
    top_score = float(result["scores"][0])

    # Decide allowance:
    # - If user provided wanted labels (either via request or stored), then allowed if top_label is in those wanted labels.
    # - If no user-specified labels and we're using DEFAULT_LABELS, treat "educational" as the allowed label by default
    allowed = False
    if wanted and len(wanted) > 0:
        allowed = top_label in wanted
    else:
        # default behaviour: show only "educational" items (this matches your original intent)
        allowed = top_label == "educational"

    # Log analytics (anonymized)
    client_ip = request.client.host if request.client else None
    log_event({
        "event": "classify",
        "client_id": video.client_id,
        "top_label": top_label,
        "top_score": round(top_score, 4),
        "candidate_labels": candidate_labels,
        "allowed": allowed,
        "client_ip": client_ip
    })

    # Build readable scores dict
    scores = {label.lower(): round(score, 4) for label, score in zip(result["labels"], result["scores"])}

    return {
        "allowed": allowed,
        "top_label": top_label,
        "confidence": round(top_score, 4),
        "scores": scores,
        "used_candidate_labels": candidate_labels
    }

@app.post("/track", summary="Log arbitrary analytic events from the extension.")
def track(event: Dict[str, Any], request: Request):
    """
    Generic tracker endpoint. Keep the payload small and anonymous where possible.
    Example payload from the extension:
    { "event": "install" } or { "event": "view_allowed", "top_label": "educational" }
    """
    client_ip = request.client.host if request.client else None
    event_record = {
        "event": event,
        "client_ip": client_ip,
        "ts": now_ts()
    }
    analytics_log.append(event_record)
    return {"status": "ok", "logged": True}

@app.get("/analytics", summary="Return the in-memory analytics log (for debugging).")
def analytics():
    """
    Simple analytics for dev/testing. In production, connect to a DB (e.g., Firestore, Supabase, MongoDB).
    """
    # Basic summary
    total = len(analytics_log)
    # counts per event name (if structured as {"event": {"event": "name", ...}})
    summary = {}
    for entry in analytics_log:
        ev = entry.get("event")
        if isinstance(ev, dict) and "event" in ev:
            name = ev["event"]
        elif isinstance(ev, str):
            name = ev
        else:
            name = "other"
        summary[name] = summary.get(name, 0) + 1

    return {"total_events": total, "summary": summary, "raw": analytics_log}
