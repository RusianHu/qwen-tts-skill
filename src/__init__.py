"""Qwen TTS Skill - Main module exports

This module provides the Claude Skill interface for Qwen TTS service.
"""

from .qwen_tts_skill import (
    QwenTTSSkill,
    TTSResult,
    Voice,
    Language,
    skill_start,
    skill_say,
    skill_voices,
)

__all__ = [
    "QwenTTSSkill",
    "TTSResult",
    "Voice",
    "Language",
    "skill_start",
    "skill_say",
    "skill_voices",
]

__version__ = "0.1.0"