"""Skill interface for Claude Code integration

This module provides the standard skill interface that Claude Code uses
to discover and invoke skill capabilities.
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from qwen_tts_skill import QwenTTSSkill, TTSResult, skill_voices, skill_say

# Skill metadata
SKILL_NAME = "qwen-tts"
SKILL_VERSION = "0.1.0"
SKILL_DESCRIPTION = "Qwen TTS to OpenAI Speech API - Text-to-speech synthesis"


class SkillInterface:
    """Standard skill interface for Claude Code"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.port = self.config.get("port", 8825)
        self.host = self.config.get("host", "127.0.0.1")
        self.api_key = self.config.get("api_key")
        self._skill: Optional[QwenTTSSkill] = None

    def _get_skill(self) -> QwenTTSSkill:
        if self._skill is None:
            self._skill = QwenTTSSkill(
                host=self.host,
                port=self.port,
                api_key=self.api_key,
                auto_start=True
            )
        return self._skill

    # === Capability: status ===
    def status(self) -> Dict[str, Any]:
        """Get skill status"""
        skill = self._get_skill()
        return {
            "running": skill.is_running,
            "url": f"http://{skill.host}:{skill.port}",
            "version": SKILL_VERSION,
        }

    # === Capability: start ===
    def start(self) -> Dict[str, Any]:
        """Start the TTS service"""
        skill = self._get_skill()
        success = skill.start_service()
        return {
            "success": success,
            "message": "Service started" if success else "Failed to start",
        }

    # === Capability: stop ===
    def stop(self) -> Dict[str, Any]:
        """Stop the TTS service"""
        skill = self._get_skill()
        success = skill.stop_service()
        return {
            "success": success,
            "message": "Service stopped" if success else "Not running",
        }

    # === Capability: voices ===
    def voices(self) -> List[Dict[str, str]]:
        """Get available voices"""
        return skill_voices(self.port)

    # === Capability: synthesize ===
    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        output: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Synthesize speech from text

        Args:
            text: Text to synthesize
            voice: Voice ID (e.g., 'vivian', 'ethan')
            language: Language ID (e.g., 'auto', 'zh')
            output: Output file path

        Returns:
            Result dict with success, audio_path, error
        """
        skill = self._get_skill()
        result = skill.synthesize(
            text=text,
            voice_id=voice,
            language_id=language,
            output_path=output
        )
        return {
            "success": result.success,
            "audio_path": result.audio_path,
            "voice_id": result.voice_id,
            "language_id": result.language_id,
            "error": result.error_message,
        }

    # === Capability: say ===
    def say(self, text: str, voice: Optional[str] = None) -> Optional[str]:
        """
        Quick synthesize - returns audio path

        Args:
            text: Text to speak
            voice: Optional voice ID

        Returns:
            Path to audio file or None
        """
        return skill_say(text, voice, self.port)


# === Claude Code skill entry points ===

def skill(config: Optional[Dict[str, Any]] = None) -> SkillInterface:
    """Factory function to create skill instance"""
    return SkillInterface(config)


def execute(command: str, args: Dict[str, Any], config: Optional[Dict[str, Any]] = None) -> Any:
    """Execute a skill command (Claude Code entry point)"""
    interface = SkillInterface(config)

    commands = {
        "status": interface.status,
        "start": interface.start,
        "stop": interface.stop,
        "voices": interface.voices,
        "synthesize": interface.synthesize,
        "say": interface.say,
    }

    if command not in commands:
        return {"error": f"Unknown command: {command}"}

    handler = commands[command]
    return handler(**args)


# === CLI interface ===
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Qwen TTS Skill Interface")
    parser.add_argument("command", choices=["status", "start", "stop", "voices", "synthesize", "say"])
    parser.add_argument("--text", "-t", help="Text to synthesize")
    parser.add_argument("--voice", "-v", help="Voice ID")
    parser.add_argument("--language", "-l", help="Language ID")
    parser.add_argument("--output", "-o", help="Output file path")
    parser.add_argument("--port", type=int, default=8825, help="Service port")

    args = parser.parse_args()

    config = {"port": args.port}
    skill = SkillInterface(config)

    if args.command == "status":
        result = skill.status()
    elif args.command == "start":
        result = skill.start()
    elif args.command == "stop":
        result = skill.stop()
    elif args.command == "voices":
        result = skill.voices()
    elif args.command == "synthesize":
        if not args.text:
            print("Error: --text required for synthesize")
            sys.exit(1)
        result = skill.synthesize(
            text=args.text,
            voice=args.voice,
            language=args.language,
            output=args.output
        )
    elif args.command == "say":
        if not args.text:
            print("Error: --text required for say")
            sys.exit(1)
        result = skill.say(args.text, args.voice)
    else:
        result = {"error": "Unknown command"}

    print(json.dumps(result, indent=2, ensure_ascii=False))
