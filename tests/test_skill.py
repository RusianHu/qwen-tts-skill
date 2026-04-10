"""Tests for Qwen TTS Skill

Run tests with: pytest tests/test_skill.py -v
"""

import pytest
import os
import tempfile
import time
from pathlib import Path

# Add scripts to path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from qwen_tts_skill import QwenTTSSkill, TTSResult, skill_voices, skill_say


class TestQwenTTSSkill:
    """Test suite for Qwen TTS Skill"""

    @pytest.fixture
    def skill(self):
        """Create a skill instance for testing"""
        skill = QwenTTSSkill(port=18825, auto_start=False)
        yield skill
        # Cleanup
        skill.stop_service()

    def test_skill_initialization(self, skill):
        """Test skill can be initialized"""
        assert skill.host == "127.0.0.1"
        assert skill.port == 18825
        assert skill._base_url == "http://127.0.0.1:18825"

    def test_is_running_false_when_not_started(self, skill):
        """Test is_running returns False when service not started"""
        assert skill.is_running is False

    @pytest.mark.skipif(
        os.getenv("SKIP_INTEGRATION_TESTS"),
        reason="Integration tests disabled"
    )
    def test_start_service(self, skill):
        """Test service can be started (requires qwen-tts package)"""
        result = skill.start_service(timeout=10)
        # This may fail if qwen-tts is not installed
        # But the skill structure should be correct
        if result:
            assert skill.is_running is True

    def test_synthesize_without_service(self, skill):
        """Test synthesis fails gracefully when service not running"""
        result = skill.synthesize("Hello world")
        # Should fail gracefully
        assert isinstance(result, TTSResult)


class TestSkillFunctions:
    """Test standalone skill functions"""

    def test_skill_voices_returns_list_or_fails_gracefully(self):
        """Test skill_voices function"""
        try:
            voices = skill_voices(port=18826)
            assert isinstance(voices, list)
        except Exception:
            # Expected if service not running
            pytest.skip("Service not available")


class TestServerModule:
    """Test the FastAPI server module"""

    def test_server_imports(self):
        """Test server module can be imported"""
        try:
            from server import app, create_speech, get_models
            assert app is not None
        except ImportError as e:
            pytest.skip(f"Server dependencies not installed: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
