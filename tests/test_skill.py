from __future__ import annotations

import sys
from pathlib import Path

import pytest
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import qwen_tts_skill as skill_module
from qwen_tts_skill import QwenTTSSkill, TTSResult


class TestSkillCore:
    def test_skill_can_be_created_without_network(self):
        skill = QwenTTSSkill(port=18825, auto_start=False)

        info = skill.get_api_info()
        assert skill.host == "127.0.0.1"
        assert skill.port == 18825
        assert info["python_api_mode"] == "direct-backend"
        assert info["rest_mode"] == "optional"
        assert info["independent"] is True
        assert info["backend"] == "internal-gradio-adapter"

    def test_tts_result_can_save_file(self, tmp_path: Path):
        output_path = tmp_path / "sample.wav"
        result = TTSResult(success=True, audio_data=b"RIFFdemo")

        saved = result.save_to_file(str(output_path))

        assert saved is True
        assert output_path.read_bytes() == b"RIFFdemo"
        assert result.audio_path == str(output_path)


class TestOptionalRestDependencies:
    def test_build_missing_rest_dependencies_message_contains_install_hint(self):
        message = skill_module.build_missing_rest_dependencies_message(
            ["fastapi>=0.100.0", "uvicorn>=0.20.0"]
        )

        assert "缺少可选 REST 服务依赖" in message
        assert "fastapi>=0.100.0" in message
        assert "uvicorn>=0.20.0" in message
        assert "requirements.txt" in message
        assert "pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt" in message

    def test_server_entrypoint_imports_from_scripts_directory(self):
        import server

        assert callable(server.main)
        assert server.HTTP_PORT == 8825

    def test_service_start_returns_false_when_rest_dependencies_missing(self, monkeypatch: pytest.MonkeyPatch):
        service = skill_module.QwenTTSService(port=18826)

        monkeypatch.setattr(
            skill_module,
            "get_missing_rest_dependencies",
            lambda: ["fastapi>=0.100.0"],
        )
        monkeypatch.setattr(
            skill_module.requests,
            "get",
            lambda *args, **kwargs: (_ for _ in ()).throw(requests.RequestException("offline")),
        )

        popen_called = False

        def fake_popen(*args, **kwargs):
            nonlocal popen_called
            popen_called = True
            raise AssertionError("缺少依赖时不应启动子进程")

        monkeypatch.setattr(skill_module.subprocess, "Popen", fake_popen)

        started = service.start(wait=False)

        assert started is False
        assert popen_called is False

    def test_create_app_raises_runtime_error_when_rest_dependencies_missing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            skill_module,
            "get_missing_rest_dependencies",
            lambda: ["fastapi>=0.100.0"],
        )

        with pytest.raises(RuntimeError, match="缺少可选 REST 服务依赖"):
            skill_module.create_app(upstream_url="https://example.com")

    def test_start_server_raises_runtime_error_when_rest_dependencies_missing(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            skill_module,
            "get_missing_rest_dependencies",
            lambda: ["uvicorn>=0.20.0"],
        )

        with pytest.raises(RuntimeError, match="缺少可选 REST 服务依赖"):
            skill_module.start_server(port=18827)
