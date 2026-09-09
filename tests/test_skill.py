from __future__ import annotations

import os
import socket
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
        backend = QwenTTSBackend(
            upstream_url="https://example.com", upstream_api_key="upstream-secret"
        )

        backend._create_client()

        assert captured["src"] == "https://example.com"
        assert captured["kwargs"]["headers"]["Authorization"] == "Bearer upstream-secret"


class TestCredentialBoundary:
    """凭据边界（P0）：本地 REST 密钥绝不能作为 Bearer 发给远端上游。"""

    class _CaptureClient:
        """记录构造参数的 fake Client。"""

        instances: list = []

        def __init__(self, src, **kwargs):
            type(self).instances.append({"src": src, "kwargs": kwargs})

        def close(self):
            pass

    @pytest.fixture(autouse=True)
    def _patch_client(self, monkeypatch: pytest.MonkeyPatch):
        type(self)._CaptureClient.instances = []
        monkeypatch.setattr(skill_module, "Client", self._CaptureClient)

    def test_local_rest_key_never_reaches_upstream(self, monkeypatch: pytest.MonkeyPatch):
        """为保护本地端口设的 API_KEY 不得出现在远端请求头里。"""
        monkeypatch.setenv("API_KEY", "local-secret")
        monkeypatch.delenv("QWEN_TTS_UPSTREAM_API_KEY", raising=False)

        QwenTTSBackend(upstream_url="https://example.com")._create_client()

        kwargs = self._CaptureClient.instances[0]["kwargs"]
        assert "Authorization" not in kwargs.get("headers", {})

    def test_explicit_upstream_key_is_sent(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("QWEN_TTS_UPSTREAM_API_KEY", "upstream-secret")
        monkeypatch.setenv("API_KEY", "local-secret")

        QwenTTSBackend(upstream_url="https://example.com")._create_client()

        headers = self._CaptureClient.instances[0]["kwargs"]["headers"]
        assert headers["Authorization"] == "Bearer upstream-secret"

    def test_rest_key_resolution_prefers_dedicated_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("QWEN_TTS_REST_API_KEY", "rest-key")
        monkeypatch.setenv("API_KEY", "legacy-key")

        assert skill_module.resolve_rest_api_key() == "rest-key"

    def test_rest_key_falls_back_to_legacy_with_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        monkeypatch.delenv("QWEN_TTS_REST_API_KEY", raising=False)
        monkeypatch.setenv("API_KEY", "legacy-key")

        with caplog.at_level("WARNING", logger="qwen_tts_skill"):
            assert skill_module.resolve_rest_api_key() == "legacy-key"

        assert any("已废弃" in r.message for r in caplog.records)

    def test_service_auto_uses_own_rest_key(self, monkeypatch: pytest.MonkeyPatch):
        """P1-7：服务启用鉴权时，实例自己的 key 必须自动生效。"""
        captured: dict = {}

        class FakeResp:
            status_code = 200
            headers = {"X-Voice-Id": "vivian", "X-Language-Id": "auto"}

            def raise_for_status(self):
                return None

            def iter_content(self, chunk_size=None):
                yield b"RIFFdemo"

        def fake_post(url, json=None, headers=None, **kwargs):
            captured["headers"] = headers
            return FakeResp()

        monkeypatch.setattr(skill_module.requests, "post", fake_post)
        monkeypatch.setattr(
            skill_module.QwenTTSService, "is_running", property(lambda self: True)
        )
        service = skill_module.QwenTTSService(port=18830, api_key="my-rest-key")
        service._voices = {"vivian": "Vivian / 十三"}

        result = service.synthesize("你好")

        assert result.success is True
        assert captured["headers"]["Authorization"] == "Bearer my-rest-key"


class TestCatalogFailureAmplification:
    """P1-5/P2-14：上游故障时 catalog 刷新不得被 resolver 放大。"""

    def test_refresh_catalog_counts_are_bounded_when_upstream_down(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        calls = {"n": 0}

        def boom(*args, **kwargs):
            calls["n"] += 1
            raise RuntimeError("upstream down")

        backend = QwenTTSBackend(upstream_url="https://unreachable.invalid")
        backend.max_attempts = 3
        backend.retry_delay = 0
        monkeypatch.setattr(backend, "_create_client", boom)

        result = backend.synthesize("你好", "vivian", "zh")

        assert result.success is False
        # 一次合成（含 3 次重试）+ 显式 ensure —— 不能随 resolver 数量倍增
        assert calls["n"] <= 4, f"catalog fetch 被放大到 {calls['n']} 次"

    def test_empty_catalog_result_keeps_old_cache(self, monkeypatch: pytest.MonkeyPatch):
        backend = QwenTTSBackend(upstream_url="https://example.com")
        backend._voices = {"vivian": "Vivian / 十三"}
        backend._languages = {"auto": "Auto / 自动"}
        backend._voice_index = {backend._canonical_key("vivian"): "vivian"}

        class EmptyClient:
            endpoints: dict = {}

            def close(self):
                pass

        monkeypatch.setattr(backend, "_create_client", lambda: EmptyClient())

        assert backend.refresh_catalog(force=True) is False
        assert backend.voices == {"vivian": "Vivian / 十三"}, "空结果不得清空有效缓存"

    def test_catalog_backoff_skips_repeated_probes(self, monkeypatch: pytest.MonkeyPatch):
        calls = {"n": 0}

        def boom(*args, **kwargs):
            calls["n"] += 1
            raise RuntimeError("down")

        backend = QwenTTSBackend(upstream_url="https://unreachable.invalid")
        monkeypatch.setattr(backend, "_create_client", boom)

        backend.ensure_catalog()
        backend.ensure_catalog()
        backend.ensure_catalog()

        assert calls["n"] == 1, "失败后的 TTL 内不应重复探测上游"


class TestCliExitCodes:
    """P1-6：CLI 失败必须返回非零退出码，供 Agent / shell 判断。"""

    def _run(self, *args):
        import subprocess

        script = BASE_DIR / "scripts" / "qwen_tts_skill.py"
        return subprocess.run(
            [sys.executable, str(script), *args],
            capture_output=True,
            # CLI 已强制 UTF-8 输出；父进程必须显式按 UTF-8 解码，
            # 否则 Windows runner（cp1252）会因中文帮助文本解码崩溃
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

    def test_say_failure_returns_nonzero(self, monkeypatch: pytest.MonkeyPatch):
        # 用一个必然连不上的上游地址，走真实 CLI 进程
        proc = self._run(
            "--say", "测试", "--base-url", "https://unreachable.invalid", "--json"
        )
        assert proc.returncode != 0, f"合成失败应返回非零，实际 {proc.returncode}"
        assert '"success": false' in proc.stdout.replace("False", "false").lower() or "失败" in proc.stdout

    def test_list_voices_failure_returns_nonzero(self):
        proc = self._run(
            "--list-voices", "--base-url", "https://unreachable.invalid", "--json"
        )
        assert proc.returncode != 0

    def test_mutually_exclusive_flags_exit_2(self):
        proc = self._run("--say", "a", "--list-voices")
        assert proc.returncode == 2


class TestRestNonBlocking:
    """issue #1 验收：慢合成阻塞期间 /health 必须仍能及时响应（event loop 不被占死）。"""

    def test_health_responsive_during_slow_synthesis(self, monkeypatch: pytest.MonkeyPatch):
        import threading
        import time

        import requests
        import uvicorn

        slow_seconds = 1.5

        def fake_slow_synthesize(self, text, voice=None, language=None, max_attempts=None):
            time.sleep(slow_seconds)
            return TTSResult(success=True, audio_data=b"RIFFdemo", voice_id="vivian")

        monkeypatch.setattr(QwenTTSBackend, "synthesize", fake_slow_synthesize)
        monkeypatch.setattr(
            QwenTTSBackend, "refresh_catalog", lambda self, force=False: True
        )

        app = skill_module.create_app(upstream_url="https://example.com")

        # 找一个空闲端口
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()

        base = f"http://127.0.0.1:{port}"
        try:
            # 等服务就绪
            deadline = time.time() + 10
            while time.time() < deadline:
                try:
                    requests.get(f"{base}/health", timeout=1)
                    break
                except requests.RequestException:
                    time.sleep(0.1)
            else:
                pytest.fail("REST 服务 10s 内未就绪")

            # 后台发起慢合成
            speech_status: dict = {}

            def slow_call():
                r = requests.post(
                    f"{base}/v1/audio/speech",
                    json={"input": "慢合成测试"},
                    timeout=30,
                )
                speech_status["code"] = r.status_code

            worker = threading.Thread(target=slow_call, daemon=True)
            worker.start()

            time.sleep(0.4)  # 确保合成请求已进入处理

            # 关键断言：合成阻塞期间 /health 必须迅速返回
            t = time.time()
            resp = requests.get(f"{base}/health", timeout=5)
            elapsed = time.time() - t

            assert resp.status_code == 200
            assert elapsed < slow_seconds / 2, (
                f"/health 耗时 {elapsed:.2f}s —— event loop 疑似被同步合成阻塞"
            )

            worker.join(timeout=10)
            assert speech_status.get("code") == 200
        finally:
            server.should_exit = True
            thread.join(timeout=5)


class TestSkillDistributionLayout:
    """issue #1 验收：skill 可原样复制进客户端 skills 目录并通过结构校验。"""

    def _copy_distribution(self, dest: Path) -> None:
        import shutil

        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(BASE_DIR / "SKILL.md", dest / "SKILL.md")
        shutil.copy2(BASE_DIR / "README.md", dest / "README.md")
        shutil.copytree(
            BASE_DIR / "scripts",
            dest / "scripts",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
        )

    def test_install_layout_matches_client_conventions(self, tmp_path: Path):
        """模拟安装到 Claude Code / Codex 的 skills 目录后，结构与规范一致。"""
        import re

        # 客户端约定：~/.claude/skills/<name>/ 与 ~/.agents/skills/<name>/
        for client_dir in (".claude", ".agents"):
            dest = tmp_path / client_dir / "skills" / "qwen-tts-skill"
            self._copy_distribution(dest)

            skill_md = (dest / "SKILL.md").read_text(encoding="utf-8")
            name = re.search(r"^name:\s*(\S+)", skill_md, re.MULTILINE).group(1)

            # 开放规范：name 必须匹配安装目录名
            assert name == dest.name, f"{client_dir}: name={name} != 目录 {dest.name}"
            assert (dest / "scripts" / "qwen_tts_skill.py").is_file()
            assert (dest / "scripts" / "server.py").is_file()

    def test_script_runs_from_installed_location(self, tmp_path: Path):
        """从安装位置以绝对路径调用 CLI，--help 正常退出（不触网）。"""
        import subprocess

        dest = tmp_path / ".claude" / "skills" / "qwen-tts-skill"
        self._copy_distribution(dest)

        proc = subprocess.run(
            [sys.executable, str(dest / "scripts" / "qwen_tts_skill.py"), "--help"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr
        assert "--say" in proc.stdout


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

    def test_license_declared_consistently(self):
        """P0-2：LICENSE 文件、pyproject、README 的许可证声明必须一致。"""
        license_text = (BASE_DIR / "LICENSE").read_text(encoding="utf-8")

        pyproject = (BASE_DIR / "pyproject.toml").read_text(encoding="utf-8")
        readme = (BASE_DIR / "README.md").read_text(encoding="utf-8")

        is_mit = "MIT License" in license_text
        is_apache = "Apache License" in license_text
        assert is_mit != is_apache, "LICENSE 文件内容无法唯一判定许可证类型"

        if is_mit:
            declared = "MIT"
            assert "Apache License" not in license_text[:200]
        else:
            declared = "Apache-2.0"
            assert "Apache License" in license_text[:200]

        assert f'license = {{text = "{declared}"}}' in pyproject, (
            f"pyproject.toml 声明的许可证与 LICENSE 文件（{declared}）不一致"
        )
        assert declared in readme, f"README 中缺少 {declared} 许可证声明"

    def test_skill_name_matches_distribution_dir(self):
        """P1-3：Agent Skills 规范要求 frontmatter name 与分发目录名一致。"""
        import re

        skill_md = (BASE_DIR / "SKILL.md").read_text(encoding="utf-8")
        match = re.search(r"^name:\s*(\S+)", skill_md, re.MULTILINE)

        assert match is not None, "SKILL.md 缺少 name 字段"
        assert match.group(1) == BASE_DIR.name, (
            f"SKILL.md name={match.group(1)!r} 与分发目录名 {BASE_DIR.name!r} 不一致"
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
