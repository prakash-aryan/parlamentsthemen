import hashlib
import os
import threading
import time
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from parltopics.db import read_env

ROOT = Path(os.environ.get("PARLTOPICS_ROOT", Path(__file__).resolve().parents[2]))
read_env(ROOT / ".env")
API = os.environ.get("ELEVENLABS_BASE_URL") or "https://api.elevenlabs.io/v1"
KEY_FILE = Path(os.environ.get("ELEVENLABS_API_KEY_FILE", Path.home() / ".config/elevenlabs/api_key"))
VOICE = os.environ.get("ELEVENLABS_VOICE_ID") or "XrExE9yKIg1WjnnlVkGX"
TTS_MODEL = os.environ.get("ELEVENLABS_MODEL") or "eleven_v4_turbo"
STT_MODEL = os.environ.get("ELEVENLABS_STT_MODEL") or "scribe_v2"
CACHE = Path(os.environ.get("PARLTOPICS_SPEECH_CACHE", ROOT / "runs" / "speech"))
DAILY_CHARS = int(os.environ.get("PARLTOPICS_SPEECH_DAILY_CHARS", "20000"))
MAX_TEXT = 1500
MAX_AUDIO = 3_000_000
# Romansh has no language code in the ElevenLabs models; without one the model detects it from the text.
CODES = {"de", "fr", "it", "en"}
ISO3 = {"deu": "de", "fra": "fr", "ita": "it", "roh": "rm", "eng": "en"}

router = APIRouter(prefix="/speech")
_lock = threading.Lock()
_used = {"day": "", "chars": 0}


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    lang: str = Field("de", pattern="^(de|fr|it|rm|en)$")


def api_key() -> str | None:
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip() or None
    return None


def spend(chars: int) -> None:
    today = time.strftime("%Y-%m-%d")
    with _lock:
        if _used["day"] != today:
            _used.update(day=today, chars=0)
        if _used["chars"] + chars > DAILY_CHARS:
            raise HTTPException(429, "daily read-aloud limit reached")
        _used["chars"] += chars


def audio(data: bytes) -> Response:
    return Response(data, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=604800"})


@router.get("")
def status():
    on = api_key() is not None
    return {"read_aloud": on, "voice_search": on}


@router.post("")
def speak(req: SpeechRequest):
    key = api_key()
    if not key:
        raise HTTPException(503, "read-aloud is not configured")
    text = " ".join(req.text.split())
    path = CACHE / f"{hashlib.sha256(f'{TTS_MODEL}|{VOICE}|{req.lang}|{text}'.encode()).hexdigest()}.mp3"
    if path.exists():
        return audio(path.read_bytes())
    spend(len(text))
    body = {"text": text, "model_id": TTS_MODEL}
    if req.lang in CODES:
        body["language_code"] = req.lang
    try:
        r = httpx.post(f"{API}/text-to-speech/{VOICE}", params={"output_format": "mp3_44100_96"},
                       headers={"xi-api-key": key}, json=body, timeout=30)
    except httpx.HTTPError:
        raise HTTPException(502, "speech service unreachable")
    if r.status_code != 200:
        raise HTTPException(502, f"speech service returned {r.status_code}")
    CACHE.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_bytes(r.content)
    part.replace(path)
    return audio(r.content)


@router.post("/transcribe")
async def transcribe(request: Request):
    key = api_key()
    if not key:
        raise HTTPException(503, "voice search is not configured")
    data = await request.body()
    if not 1000 <= len(data) <= MAX_AUDIO:
        raise HTTPException(413 if len(data) > MAX_AUDIO else 400, "recording too long or too short")
    kind = request.headers.get("content-type", "audio/webm").split(";")[0]
    try:
        r = httpx.post(f"{API}/speech-to-text", headers={"xi-api-key": key}, data={"model_id": STT_MODEL},
                       files={"file": (f"query.{kind.split('/')[-1]}", data, kind)}, timeout=30)
    except httpx.HTTPError:
        raise HTTPException(502, "speech service unreachable")
    if r.status_code != 200:
        raise HTTPException(502, f"speech service returned {r.status_code}")
    out = r.json()
    return {"text": (out.get("text") or "").strip().rstrip(".!?").strip(), "lang": ISO3.get(out.get("language_code") or "")}
