from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import qwen_tts_skill as skill_module
from qwen_tts_skill import QwenTTSSkill, QwenTTSBackend, TTSResult

# 真实上游调用的用例默认跳过：它们依赖网络且耗时较长（单次约 10s）。
# 需要验证真实链路时设置：QWEN_TTS_NETWORK_TESTS=1
RUN_NETWORK_TESTS = os.getenv("QWEN_TTS_NETWORK_TESTS") == "1"
network = pytest.mark.skipif(
    not RUN_NETWORK_TESTS,
    reason="需要真实上游，设置 QWEN_TTS_NETWORK_TESTS=1 后运行",
)


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


class TestUpstreamResolution:
    """语言别名与音色容错匹配的离线单测。

    这两项是 2026-09 上游体检中发现的存量缺陷：
    调用方按文档传 `zh` / `en` 会被静默回退成 auto，传 `ono-anna` 匹配不到 `ono anna`。
    """

    def _backend_with_catalog(self) -> QwenTTSBackend:
        backend = QwenTTSBackend(upstream_url="https://example.com")
        # 直接灌入目录，避免真实网络请求
        backend._voices = {
            "vivian": "Vivian / 十三",
            "ono anna": "Ono Anna / 日语-小野杏",
            "radio gol": "Radio Gol / 葡萄牙语巴-拉迪奥·戈尔",
        }
        backend._voice_index = {
            backend._canonical_key(vid): vid for vid in backend._voices
        }
        backend._languages = {
            "auto": "Auto / 自动",
            "chinese": "Chinese / 中文",
            "english": "English / 英文",
            "japanese": "Japanese / 日语",
        }
        backend._default_voice_id = "vivian"
        backend._default_language_id = "auto"
        return backend

    @pytest.mark.parametrize(
        "given,expected",
        [
            ("zh", "chinese"),
            ("cn", "chinese"),
            ("zh-CN", "chinese"),
            ("中文", "chinese"),
            ("en", "english"),
            ("en-US", "english"),
            ("ja", "japanese"),
            ("auto", "auto"),
            ("chinese", "chinese"),
        ],
    )
    def test_language_alias_resolves_to_upstream_id(self, given: str, expected: str):
        backend = self._backend_with_catalog()

        assert backend._resolve_language_id(given) == expected

    def test_unknown_language_falls_back_to_default(self):
        backend = self._backend_with_catalog()

        assert backend._resolve_language_id("xx") == "auto"
        assert backend._resolve_language_id(None) == "auto"

    @pytest.mark.parametrize(
        "given,expected",
        [
            ("ono anna", "ono anna"),
            ("ono-anna", "ono anna"),
            ("onoanna", "ono anna"),
            ("Ono Anna", "ono anna"),
            ("radio gol", "radio gol"),
            ("radio_gol", "radio gol"),
        ],
    )
    def test_voice_id_matching_tolerates_spaces_and_separators(self, given: str, expected: str):
        backend = self._backend_with_catalog()

        assert backend._resolve_voice_id(given) == expected

    def test_unknown_voice_falls_back_to_default(self):
        backend = self._backend_with_catalog()

        assert backend._resolve_voice_id("nonexistent") == "vivian"


class TestUpstreamFailureIsGraceful:
    """上游不可达时必须优雅降级，不能抛异常。

    早期实现里 `Client(...)` 的构造在 try 块之外，上游一挂就冒泡，
    导致 CLI 崩溃、FastAPI lifespan 失败（服务完全起不来）。
    """

    def test_refresh_catalog_returns_false_instead_of_raising(self, monkeypatch: pytest.MonkeyPatch):
        backend = QwenTTSBackend(upstream_url="https://unreachable.invalid")

        def boom(*args, **kwargs):
            raise RuntimeError("Could not fetch config")

        monkeypatch.setattr(backend, "_create_client", boom)

        assert backend.refresh_catalog(force=True) is False

    def test_synthesize_returns_failure_instead_of_raising_on_connect_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """synthesize 里 Client 构造也必须纳入 try，否则上游超时会直接崩。"""
        backend = QwenTTSBackend(upstream_url="https://unreachable.invalid")
        backend.max_attempts = 1
        backend._voices = {"vivian": "Vivian / 十三"}
        backend._languages = {"auto": "Auto / 自动"}
        backend._default_voice_id = "vivian"

        def boom(*args, **kwargs):
            raise TimeoutError("The handshake operation timed out")

        monkeypatch.setattr(backend, "_create_client", boom)

        result = backend.synthesize("你好")

        assert result.success is False
        assert "上游语音合成失败" in (result.error_message or "")

    def test_synthesize_retries_then_succeeds(self, monkeypatch: pytest.MonkeyPatch):
        """上游偶发抖动时重试应能救回（实测 49 音色中 maia 首次失败、重试成功）。"""
        backend = QwenTTSBackend(upstream_url="https://example.com")
        backend.max_attempts = 3
        backend.retry_delay = 0
        calls = {"n": 0}

        def flaky(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] < 3:
                return TTSResult(success=False, error_message="upstream AppError")
            return TTSResult(success=True, audio_data=b"RIFFdemo", voice_id="vivian")

        monkeypatch.setattr(backend, "_synthesize_once", flaky)

        result = backend.synthesize("你好")

        assert result.success is True
        assert calls["n"] == 3

    def test_synthesize_gives_up_after_max_attempts(self, monkeypatch: pytest.MonkeyPatch):
        backend = QwenTTSBackend(upstream_url="https://example.com")
        backend.max_attempts = 2
        backend.retry_delay = 0
        calls = {"n": 0}

        def always_fail(*args, **kwargs):
            calls["n"] += 1
            return TTSResult(success=False, error_message="upstream down")

        monkeypatch.setattr(backend, "_synthesize_once", always_fail)

        result = backend.synthesize("你好")

        assert result.success is False
        assert calls["n"] == 2

    def test_api_key_is_forwarded_to_upstream_client(self, monkeypatch: pytest.MonkeyPatch):
        captured: dict = {}

        class FakeClient:
            def __init__(self, src, **kwargs):
                captured["src"] = src
                captured["kwargs"] = kwargs

            def close(self):
                pass

        monkeypatch.setattr(skill_module, "Client", FakeClient)
        backend = QwenTTSBackend(upstream_url="https://example.com", api_key="sk-test")

        backend._create_client()

        assert captured["src"] == "https://example.com"
        assert captured["kwargs"]["headers"]["Authorization"] == "Bearer sk-test"


class TestReleaseConsistency:
    """发布一致性校验：防止版本号在多处硬编码后漂移。"""

    def test_pyproject_version_matches_module_version(self):
        import re

        pyproject = (BASE_DIR / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)

        assert match is not None, "pyproject.toml 中未找到 version 字段"
        assert match.group(1) == skill_module.__version__, (
            f"版本号不一致：pyproject.toml={match.group(1)} "
            f"scripts/qwen_tts_skill.py={skill_module.__version__}"
        )

    def test_version_is_semver(self):
        import re

        assert re.match(r"^\d+\.\d+\.\d+$", skill_module.__version__), (
            f"版本号不符合语义化格式: {skill_module.__version__}"
        )


@network
class TestRealUpstreamSmoke:
    """真实上游冒烟测试（默认跳过）。

    覆盖 SKILL.md 承诺的核心能力，用于确认上游切换/迁移后功能仍完整。
    """

    def test_catalog_can_be_fetched(self):
        backend = QwenTTSBackend()

        assert backend.refresh_catalog(force=True) is True
        assert len(backend.voices) > 0, "音色列表不应为空"
        assert len(backend.languages) > 0, "语言列表不应为空"
        assert backend.default_voice_id in backend.voices

    def test_synthesize_returns_valid_wav(self):
        backend = QwenTTSBackend()

        result = backend.synthesize("你好，这是真实上游冒烟测试。", voice="vivian", language="zh")

        assert result.success is True, result.error_message
        assert result.audio_data is not None
        # WAV 容器头
        assert result.audio_data[:4] == b"RIFF"
        assert result.audio_data[8:12] == b"WAVE"
        # 与旧上游一致的 24kHz / 单声道 / 16bit
        import io
        import wave

        with wave.open(io.BytesIO(result.audio_data)) as wav:
            assert wav.getframerate() == 24000
            assert wav.getnchannels() == 1
            assert wav.getsampwidth() == 2

    def test_language_parameter_takes_effect(self):
        """`zh` 必须真正生效，而不是静默回退成 auto。"""
        backend = QwenTTSBackend()

        result = backend.synthesize("你好。", voice="vivian", language="zh")

        assert result.success is True, result.error_message
        assert result.language_id == "chinese"
