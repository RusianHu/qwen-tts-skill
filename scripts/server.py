"""FastAPI wrapper for Qwen TTS - Alternative server implementation

Provides a standalone REST API server without the original qwen-tts package.
This can be used when the original package is not installed.
"""

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from gradio_client import Client
import aiofiles

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
BASE_URL = os.getenv("BASE_URL", "https://qwen-qwen3-tts-demo.ms.show")
API_KEY = os.getenv("API_KEY")

# Cache
VOICE_LIST: Optional[Dict[str, str]] = None
LANGUAGE_LIST: Optional[Dict[str, str]] = None


class TTSSettings:
    """TTS settings cache"""
    voices: Dict[str, str] = {}
    languages: Dict[str, str] = {}
    default_voice: str = "Vivian / 十三"
    default_language: str = "Auto / 自动"


settings = TTSSettings()


class SpeechRequest(BaseModel):
    input: str
    voice: Optional[str] = None
    language: Optional[str] = "auto"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan"""
    # Startup
    logger.info("Starting Qwen TTS Server...")
    await refresh_voices()
    yield
    # Shutdown
    logger.info("Shutting down Qwen TTS Server...")


app = FastAPI(
    title="Qwen TTS API",
    description="OpenAI-compatible Text-to-Speech API using Qwen TTS",
    version="0.1.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


async def refresh_voices():
    """Fetch voice and language lists from upstream"""
    global VOICE_LIST, LANGUAGE_LIST

    try:
        gradio = Client(BASE_URL)
        VOICE_LIST = {}
        LANGUAGE_LIST = {}

        for endpoint in gradio.endpoints.values():
            for param in endpoint.parameters_info or []:
                name = param.get("parameter_name")
                for val in param.get("type", {}).get("enum", []):
                    vid = str(val).lower().split("/")[0].strip()
                    if name == "voice_display":
                        VOICE_LIST[vid] = val
                    elif name == "language_display":
                        LANGUAGE_LIST[vid] = val

        gradio.close()

        settings.voices = VOICE_LIST
        settings.languages = LANGUAGE_LIST

        logger.info(f"Loaded {len(VOICE_LIST)} voices, {len(LANGUAGE_LIST)} languages")

    except Exception as e:
        logger.error(f"Failed to fetch voices: {e}")


@app.get("/")
async def index():
    """Health check / info"""
    return {
        "name": "Qwen TTS API",
        "version": "0.1.0",
        "upstream": BASE_URL,
    }


@app.get("/v1/models")
async def get_models():
    """Get available models, voices, and languages"""
    if not settings.voices:
        await refresh_voices()

    return {
        "data": [{"id": "qwen-tts"}],
        "voices": settings.voices,
        "languages": settings.languages,
        "default_voice": list(settings.voices.keys())[0] if settings.voices else None,
        "default_language": "auto",
        "auth_required": bool(API_KEY),
    }


@app.post("/v1/audio/speech")
async def create_speech(request: SpeechRequest):
    """Create speech from text"""
    # Check auth
    if API_KEY:
        # In real implementation, check Authorization header
        pass

    # Validate input
    text = request.input.strip()
    if not text:
        raise HTTPException(status_code=400, detail="No input text provided")

    # Get voice and language
    voice_id = (request.voice or "").lower().strip()
    language_id = (request.language or "auto").lower().strip()

    voice_name = settings.voices.get(voice_id, settings.default_voice)
    language_name = settings.languages.get(language_id, settings.default_language)

    # Generate audio using Gradio client
    try:
        gradio = Client(BASE_URL)
        audio_path = gradio.predict(
            api_name="/tts_interface",
            text=text,
            voice_display=voice_name,
            language_display=language_name,
        )
        gradio.close()

        if not audio_path or not os.path.exists(audio_path):
            raise HTTPException(status_code=500, detail="Failed to generate audio")

        logger.info(f"Generated audio: {audio_path}")

        # Stream response
        async def audio_stream():
            async with aiofiles.open(audio_path, "rb") as f:
                while True:
                    chunk = await f.read(8192)
                    if not chunk:
                        break
                    yield chunk
            # Cleanup
            if os.path.exists(audio_path):
                os.remove(audio_path)

        return StreamingResponse(
            audio_stream(),
            media_type="audio/wav",
            headers={
                "Content-Disposition": f'inline; filename="speech.wav"',
                "X-Voice-Id": voice_id or "default",
                "X-Language-Id": language_id or "auto",
            }
        )

    except Exception as e:
        logger.error(f"TTS Error: {e}")
        raise HTTPException(status_code=502, detail=f"Upstream error: {str(e)}")


@app.get("/v1/voices")
async def list_voices():
    """List available voices"""
    if not settings.voices:
        await refresh_voices()
    return {
        "voices": [
            {"id": k, "name": v}
            for k, v in settings.voices.items()
        ]
    }


def start_server(host: str = "0.0.0.0", port: int = 8825):
    """Start the server"""
    import uvicorn
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    port = int(os.getenv("HTTP_PORT", 8825))
    start_server(port=port)
