"""Qwen TTS Skill - Claude Skill for Qwen TTS REST API

This skill provides a bridge between Claude and Qwen TTS service,
enabling text-to-speech synthesis through an OpenAI-compatible API.
"""

import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Dict, List, Any, Union
from dataclasses import dataclass
import json

# Third-party imports
import requests
from aiohttp import ClientSession

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class Voice:
    """Voice model information"""
    id: str
    name: str


@dataclass
class Language:
    """Language option"""
    id: str
    name: str


@dataclass
class TTSResult:
    """TTS synthesis result"""
    success: bool
    audio_path: Optional[str] = None
    error_message: Optional[str] = None
    voice_id: Optional[str] = None
    language_id: Optional[str] = None


class QwenTTSSkill:
    """
    Claude Skill for Qwen TTS Service

    Manages the Qwen TTS REST API service and provides easy-to-use
    methods for text-to-speech synthesis.
    """

    DEFAULT_PORT = 8825
    DEFAULT_HOST = "127.0.0.1"
    BASE_URL = "https://qwen-qwen3-tts-demo.ms.show"

    def __init__(
        self,
        host: str = None,
        port: int = None,
        api_key: Optional[str] = None,
        auto_start: bool = True
    ):
        """
        Initialize Qwen TTS Skill

        Args:
            host: Service host (default: 127.0.0.1)
            port: Service port (default: 8825)
            api_key: Optional API key for authentication
            auto_start: Whether to auto-start the service
        """
        self.host = host or self.DEFAULT_HOST
        self.port = port or self.DEFAULT_PORT
        self.api_key = api_key
        self.auto_start = auto_start
        self._service_process: Optional[subprocess.Popen] = None
        self._base_url = f"http://{self.host}:{self.port}"
        self._voices: Optional[Dict[str, str]] = None
        self._languages: Optional[Dict[str, str]] = None

    @property
    def is_running(self) -> bool:
        """Check if the service is running"""
        try:
            response = requests.get(
                f"{self._base_url}/v1/models",
                timeout=2
            )
            return response.status_code == 200
        except Exception:
            return False

    def start_service(self, wait: bool = True, timeout: int = 30) -> bool:
        """
        Start the Qwen TTS service

        Args:
            wait: Whether to wait for service to be ready
            timeout: Maximum wait time in seconds

        Returns:
            True if service started successfully
        """
        if self.is_running:
            logger.info("Service is already running")
            return True

        # Set environment variables
        env = os.environ.copy()
        env["HTTP_PORT"] = str(self.port)
        env["BASE_URL"] = self.BASE_URL
        if self.api_key:
            env["API_KEY"] = self.api_key

        # Try to start service using qwen-tts command
        try:
            logger.info(f"Starting Qwen TTS service on {self.host}:{self.port}...")

            # First try: system installed qwen-tts
            try:
                result = subprocess.run(
                    ["qwen-tts", "--version"],
                    capture_output=True,
                    timeout=2
                )
                if result.returncode == 0:
                    self._service_process = subprocess.Popen(
                        ["qwen-tts"],
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                else:
                    raise FileNotFoundError()
            except (subprocess.TimeoutExpired, FileNotFoundError):
                # Second try: run from source
                skill_dir = Path(__file__).parent.parent
                qwen_tts_path = skill_dir / ".." / "qwen-tts2api" / "qwen_tts"

                if qwen_tts_path.exists():
                    sys.path.insert(0, str(qwen_tts_path.parent))
                    from qwen_tts import main
                    import threading

                    def run_service():
                        import asyncio
                        import aiohttp.web

                        app = main()
                        # This won't work directly, so we fall back

                    logger.warning("Direct module import not available, trying alternative")

                # Third try: Python module execution
                self._service_process = subprocess.Popen(
                    [sys.executable, "-m", "qwen_tts"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )

            if wait:
                start_time = time.time()
                while time.time() - start_time < timeout:
                    if self.is_running:
                        logger.info("Service is ready")
                        return True
                    time.sleep(0.5)
                    if self._service_process.poll() is not None:
                        stdout, stderr = self._service_process.communicate()
                        logger.error(f"Service exited early: {stderr.decode()}")
                        return False

                logger.error(f"Service startup timed out after {timeout}s")
                return False

            return True

        except Exception as e:
            logger.error(f"Failed to start service: {e}")
            return False

    def stop_service(self) -> bool:
        """Stop the Qwen TTS service"""
        if self._service_process:
            try:
                self._service_process.terminate()
                self._service_process.wait(timeout=5)
                self._service_process = None
                logger.info("Service stopped")
                return True
            except Exception as e:
                logger.error(f"Error stopping service: {e}")
                return False
        return True

    def get_voices(self, force_refresh: bool = False) -> Dict[str, str]:
        """
        Get available voices from the service

        Args:
            force_refresh: Force refresh voice list

        Returns:
            Dictionary of voice_id -> voice_name
        """
        if self._voices is not None and not force_refresh:
            return self._voices

        if not self.is_running and self.auto_start:
            if not self.start_service():
                raise RuntimeError("Failed to start service")

        try:
            response = requests.get(
                f"{self._base_url}/v1/models",
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            self._voices = data.get("voices", {})
            self._languages = data.get("languages", {})

            return self._voices

        except Exception as e:
            logger.error(f"Failed to get voices: {e}")
            raise

    def get_languages(self) -> Dict[str, str]:
        """
        Get available languages from the service

        Returns:
            Dictionary of language_id -> language_name
        """
        if self._languages is None:
            self.get_voices()
        return self._languages or {}

    def synthesize(
        self,
        text: str,
        voice_id: Optional[str] = None,
        language_id: Optional[str] = None,
        output_path: Optional[str] = None
    ) -> TTSResult:
        """
        Synthesize speech from text

        Args:
            text: Text to synthesize
            voice_id: Voice ID (optional, uses default if not specified)
            language_id: Language ID (optional, uses auto if not specified)
            output_path: Path to save audio file (optional, uses temp file if not specified)

        Returns:
            TTSResult with success status and audio path
        """
        if not self.is_running and self.auto_start:
            if not self.start_service():
                return TTSResult(
                    success=False,
                    error_message="Failed to start TTS service"
                )

        # Get default voice/language if not specified
        if voice_id is None or language_id is None:
            voices = self.get_voices()
            languages = self.get_languages()

            if voice_id is None:
                voice_id = list(voices.keys())[0] if voices else "vivian"
            if language_id is None:
                language_id = "auto"

        # Prepare request
        payload = {
            "input": text,
            "voice": voice_id,
            "language": language_id
        }

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            logger.info(f"Synthesizing: '{text[:50]}...' with voice={voice_id}, lang={language_id}")

            response = requests.post(
                f"{self._base_url}/v1/audio/speech",
                json=payload,
                headers=headers,
                timeout=60,
                stream=True
            )
            response.raise_for_status()

            # Determine output path
            if output_path is None:
                import tempfile
                output_path = tempfile.mktemp(suffix=".wav")

            # Save audio
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            logger.info(f"Audio saved to: {output_path}")

            return TTSResult(
                success=True,
                audio_path=output_path,
                voice_id=voice_id,
                language_id=language_id
            )

        except requests.exceptions.HTTPError as e:
            error_msg = f"HTTP Error: {e}"
            try:
                error_data = e.response.json()
                error_msg = error_data.get("error", {}).get("message", str(e))
            except:
                pass
            logger.error(error_msg)
            return TTSResult(
                success=False,
                error_message=error_msg
            )

        except Exception as e:
            error_msg = f"Synthesis failed: {e}"
            logger.error(error_msg)
            return TTSResult(
                success=False,
                error_message=error_msg
            )

    def quick_say(self, text: str, voice_id: Optional[str] = None) -> Optional[str]:
        """
        Quick text-to-speech with default settings

        Args:
            text: Text to speak
            voice_id: Optional voice override

        Returns:
            Path to audio file or None if failed
        """
        result = self.synthesize(text, voice_id=voice_id)
        return result.audio_path if result.success else None

    def __enter__(self):
        """Context manager entry"""
        if self.auto_start:
            self.start_service()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.stop_service()


# Convenience functions for direct use

def skill_start(port: int = 8825) -> QwenTTSSkill:
    """Start and return a skill instance"""
    skill = QwenTTSSkill(port=port)
    skill.start_service()
    return skill


def skill_say(text: str, voice: Optional[str] = None, port: int = 8825) -> Optional[str]:
    """Quick say function - one-shot TTS"""
    with QwenTTSSkill(port=port, auto_start=True) as skill:
        return skill.quick_say(text, voice)


def skill_voices(port: int = 8825) -> List[Dict[str, str]]:
    """Get list of available voices"""
    with QwenTTSSkill(port=port, auto_start=True) as skill:
        voices = skill.get_voices()
        return [{"id": k, "name": v} for k, v in voices.items()]


if __name__ == "__main__":
    # CLI interface
    import argparse

    parser = argparse.ArgumentParser(description="Qwen TTS Skill")
    parser.add_argument("--start", action="store_true", help="Start service")
    parser.add_argument("--stop", action="store_true", help="Stop service")
    parser.add_argument("--say", type=str, help="Text to synthesize")
    parser.add_argument("--voice", type=str, help="Voice ID")
    parser.add_argument("--list-voices", action="store_true", help="List voices")
    parser.add_argument("--port", type=int, default=8825, help="Service port")

    args = parser.parse_args()

    skill = QwenTTSSkill(port=args.port)

    if args.start:
        success = skill.start_service()
        print(f"Service {'started' if success else 'failed to start'}")

    elif args.stop:
        success = skill.stop_service()
        print(f"Service {'stopped' if success else 'not running'}")

    elif args.say:
        result = skill.synthesize(args.say, voice_id=args.voice)
        if result.success:
            print(f"Audio saved to: {result.audio_path}")
        else:
            print(f"Error: {result.error_message}")

    elif args.list_voices:
        voices = skill.get_voices()
        print("Available voices:")
        for vid, vname in voices.items():
            print(f"  - {vid}: {vname}")

    else:
        parser.print_help()
