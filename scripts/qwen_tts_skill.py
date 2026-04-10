"""
Qwen TTS Skill for Claude

将 Qwen TTS（通义千问语音合成）的远端 Gradio 接口，
封装为当前项目内置的 OpenAI 兼容 REST API 服务，
并提供便捷的 Python API 供 Claude / 普通 Python 调用。

本模块现在已经独立，不再依赖本地的 qwen-tts2api 项目或其命令行进程。
"""

from __future__ import annotations

import argparse
import base64
import io
import logging
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from gradio_client import Client
from pydantic import BaseModel

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


DEFAULT_UPSTREAM_URL = "https://qwen-qwen3-tts-demo.ms.show"
DEFAULT_API_NAME = "/tts_interface"
DEFAULT_MODEL_ID = "qwen-tts"
DEFAULT_LANGUAGE_ID = "auto"
DEFAULT_LANGUAGE_NAME = "Auto / 自动"
DEFAULT_VOICE_NAME = "Vivian / 十三"
REST_REQUIRED_PACKAGES = {
    "fastapi": "fastapi>=0.100.0",
    "uvicorn": "uvicorn>=0.20.0",
    "pydantic": "pydantic>=2.0.0",
    "gradio_client": "gradio_client>=2.0.0",
    "requests": "requests>=2.31.0",
}


def get_missing_rest_dependencies() -> List[str]:
    """返回运行可选 REST 服务时缺失的依赖包列表。"""
    missing: List[str] = []

    for module_name, package_spec in REST_REQUIRED_PACKAGES.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_spec)

    return missing


def build_missing_rest_dependencies_message(missing_dependencies: List[str]) -> str:
    """构造缺失 REST 依赖时的统一错误消息。"""
    if not missing_dependencies:
        return ""

    return (
        "缺少可选 REST 服务依赖: "
        f"{', '.join(missing_dependencies)}。"
        "请先在当前 skill 根目录执行 `pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt` 安装依赖后再启动 REST 服务。"
    )


class SpeechRequest(BaseModel):
    """REST 语音合成请求体。"""

    input: str
    voice: Optional[str] = None
    language: Optional[str] = DEFAULT_LANGUAGE_ID


@dataclass
class VoiceInfo:
    """音色信息"""

    id: str
    name: str

    @classmethod
    def from_api(cls, vid: str, name: str) -> "VoiceInfo":
        return cls(id=vid, name=name)


# 向后兼容别名
Voice = VoiceInfo


@dataclass
class Language:
    """语言选项"""

    id: str
    name: str


@dataclass
class TTSResult:
    """语音合成结果"""

    success: bool
    audio_data: Optional[bytes] = None
    audio_path: Optional[str] = None
    content_type: Optional[str] = None
    voice_id: Optional[str] = None
    language_id: Optional[str] = None
    error_message: Optional[str] = None

    def save_to_file(self, filepath: str) -> bool:
        """保存音频到文件"""
        if not self.success or not self.audio_data:
            return False

        try:
            target = Path(filepath)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self.audio_data)
            self.audio_path = str(target)
            logger.info("音频已保存到: %s", target)
            return True
        except Exception as exc:
            logger.error("保存音频失败: %s", exc)
            self.error_message = f"保存音频失败: {exc}"
            return False


class QwenTTSBackend:
    """当前项目内置的 Qwen TTS Python 适配后端。"""

    def __init__(
        self,
        upstream_url: Optional[str] = None,
        api_name: str = DEFAULT_API_NAME,
        api_key: Optional[str] = None,
    ):
        self.upstream_url = upstream_url or os.getenv("BASE_URL", DEFAULT_UPSTREAM_URL)
        self.api_name = api_name
        self.api_key = api_key or os.getenv("API_KEY")
        self._voices: Dict[str, str] = {}
        self._languages: Dict[str, str] = {}
        self._default_voice_id: Optional[str] = None
        self._default_language_id: str = DEFAULT_LANGUAGE_ID
        self._default_voice_name: str = DEFAULT_VOICE_NAME
        self._default_language_name: str = DEFAULT_LANGUAGE_NAME

    @property
    def voices(self) -> Dict[str, str]:
        return self._voices.copy()

    @property
    def languages(self) -> Dict[str, str]:
        return self._languages.copy()

    @property
    def default_voice_id(self) -> Optional[str]:
        return self._default_voice_id

    @property
    def default_language_id(self) -> str:
        return self._default_language_id

    def _create_client(self) -> Client:
        return Client(self.upstream_url)

    @staticmethod
    def _normalize_option_id(option_label: str) -> str:
        value = str(option_label or "").strip().lower()
        if not value:
            return ""
        return value.split("/")[0].strip()

    def refresh_catalog(self, force: bool = False) -> bool:
        """刷新远端音色 / 语言枚举缓存。"""
        if not force and self._voices and self._languages:
            return True

        voices: Dict[str, str] = {}
        languages: Dict[str, str] = {}
        client = self._create_client()

        try:
            for endpoint in client.endpoints.values():
                for param in endpoint.parameters_info or []:
                    name = param.get("parameter_name")
                    enum_values = param.get("type", {}).get("enum", []) or []
                    for display_name in enum_values:
                        option_id = self._normalize_option_id(display_name)
                        if not option_id:
                            continue
                        if name == "voice_display":
                            voices.setdefault(option_id, str(display_name))
                        elif name == "language_display":
                            languages.setdefault(option_id, str(display_name))
        except Exception as exc:
            logger.error("获取远端音色/语言列表失败: %s", exc)
            return False
        finally:
            try:
                client.close()
            except Exception:
                pass

        self._voices = voices
        self._languages = languages

        self._default_voice_id = self._pick_default_voice_id()
        if self._default_voice_id and self._default_voice_id in self._voices:
            self._default_voice_name = self._voices[self._default_voice_id]
        elif self._voices:
            self._default_voice_name = next(iter(self._voices.values()))

        if self._languages:
            if DEFAULT_LANGUAGE_ID in self._languages:
                self._default_language_id = DEFAULT_LANGUAGE_ID
                self._default_language_name = self._languages[DEFAULT_LANGUAGE_ID]
            else:
                self._default_language_id = next(iter(self._languages.keys()))
                self._default_language_name = self._languages[self._default_language_id]

        logger.info(
            "已加载 %s 个音色, %s 种语言, 默认音色=%s, 默认语言=%s",
            len(self._voices),
            len(self._languages),
            self._default_voice_id,
            self._default_language_id,
        )
        return True

    def _pick_default_voice_id(self) -> Optional[str]:
        if not self._voices:
            return None

        for voice_id, display_name in self._voices.items():
            voice_id_lower = voice_id.lower()
            display_lower = str(display_name).lower()
            if "vivian" in voice_id_lower or "vivian" in display_lower or "十三" in str(display_name):
                return voice_id

        return next(iter(self._voices.keys()))

    def _resolve_voice_id(self, requested_voice: Optional[str]) -> Optional[str]:
        if not self._voices:
            self.refresh_catalog()

        voice_id = (requested_voice or "").strip().lower()
        if voice_id and voice_id in self._voices:
            return voice_id
        return self._default_voice_id or self._pick_default_voice_id()

    def _resolve_language_id(self, requested_language: Optional[str]) -> str:
        if not self._languages:
            self.refresh_catalog()

        language_id = (requested_language or DEFAULT_LANGUAGE_ID).strip().lower()
        if language_id in self._languages:
            return language_id
        return self._default_language_id or DEFAULT_LANGUAGE_ID

    def _resolve_voice_name(self, requested_voice: Optional[str]) -> str:
        voice_id = self._resolve_voice_id(requested_voice)
        if voice_id and voice_id in self._voices:
            return self._voices[voice_id]
        if self._default_voice_name:
            return self._default_voice_name
        if self._voices:
            return next(iter(self._voices.values()))
        return DEFAULT_VOICE_NAME

    def _resolve_language_name(self, requested_language: Optional[str]) -> str:
        language_id = self._resolve_language_id(requested_language)
        if language_id in self._languages:
            return self._languages[language_id]
        if self._default_language_name:
            return self._default_language_name
        if self._languages:
            return next(iter(self._languages.values()))
        return DEFAULT_LANGUAGE_NAME

    def get_models_payload(self, auth_required: Optional[bool] = None) -> Dict[str, Any]:
        if not self._voices or not self._languages:
            self.refresh_catalog()

        return {
            "data": [{"id": DEFAULT_MODEL_ID}],
            "voices": self.voices,
            "languages": self.languages,
            "default_voice": self._resolve_voice_id(None),
            "default_language": self._resolve_language_id(None),
            "auth_required": bool(self.api_key) if auth_required is None else auth_required,
            "backend": "internal-gradio-adapter",
            "upstream": self.upstream_url,
        }

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
    ) -> TTSResult:
        """直接调用远端 Gradio 接口生成语音。"""
        if not text or not text.strip():
            return TTSResult(success=False, error_message="文本不能为空")

        if not self._voices or not self._languages:
            self.refresh_catalog()

        resolved_voice_id = self._resolve_voice_id(voice)
        resolved_language_id = self._resolve_language_id(language)
        resolved_voice_name = self._resolve_voice_name(resolved_voice_id)
        resolved_language_name = self._resolve_language_name(resolved_language_id)

        client = self._create_client()
        audio_path: Optional[str] = None

        try:
            logger.info(
                "开始调用上游合成语音: voice=%s(%s), language=%s(%s)",
                resolved_voice_id,
                resolved_voice_name,
                resolved_language_id,
                resolved_language_name,
            )
            audio_path = client.predict(
                api_name=self.api_name,
                text=text.strip(),
                voice_display=resolved_voice_name,
                language_display=resolved_language_name,
            )
        except Exception as exc:
            logger.error("上游语音合成失败: %s", exc, exc_info=True)
            return TTSResult(
                success=False,
                voice_id=resolved_voice_id,
                language_id=resolved_language_id,
                error_message=f"上游语音合成失败: {exc}",
            )
        finally:
            try:
                client.close()
            except Exception:
                pass

        try:
            if not audio_path or not os.path.exists(audio_path):
                return TTSResult(
                    success=False,
                    voice_id=resolved_voice_id,
                    language_id=resolved_language_id,
                    error_message="上游未返回有效音频文件",
                )

            audio_bytes = Path(audio_path).read_bytes()
            return TTSResult(
                success=True,
                audio_data=audio_bytes,
                content_type="audio/wav",
                voice_id=resolved_voice_id,
                language_id=resolved_language_id,
            )
        except Exception as exc:
            logger.error("读取音频文件失败: %s", exc, exc_info=True)
            return TTSResult(
                success=False,
                voice_id=resolved_voice_id,
                language_id=resolved_language_id,
                error_message=f"读取音频文件失败: {exc}",
            )
        finally:
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except OSError:
                    pass


class QwenTTSService:
    """Qwen TTS 本地 REST 服务管理器。"""

    DEFAULT_PORT = 8825
    DEFAULT_HOST = "127.0.0.1"

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        upstream_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.host = host or self.DEFAULT_HOST
        self.port = port or self.DEFAULT_PORT
        self.upstream_url = upstream_url or os.getenv("BASE_URL", DEFAULT_UPSTREAM_URL)
        self.api_key = api_key or os.getenv("API_KEY")
        self.base_url = f"http://{self.host}:{self.port}"
        self._process: Optional[subprocess.Popen] = None
        self._voices: Dict[str, str] = {}
        self._languages: Dict[str, str] = {}

    @property
    def is_running(self) -> bool:
        """检查本地 REST 服务是否运行。"""
        try:
            resp = requests.get(f"{self.base_url}/v1/models", timeout=2)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    @property
    def api_endpoint(self) -> str:
        """获取本地 REST API 端点。"""
        return f"{self.base_url}/v1/audio/speech"

    def _ensure_dependencies(self) -> List[str]:
        """检查独立运行 REST 服务所需依赖，返回缺失依赖列表。"""
        return get_missing_rest_dependencies()

    def start(self, wait: bool = True, timeout: int = 30) -> bool:
        """启动当前项目内置的本地 REST 服务。"""
        if self.is_running:
            logger.info("Qwen TTS REST 服务已在运行: %s", self.base_url)
            return True

        missing_dependencies = self._ensure_dependencies()
        if missing_dependencies:
            logger.error("无法启动 Qwen TTS REST 服务：%s", build_missing_rest_dependencies_message(missing_dependencies))
            return False

        server_script = Path(__file__).resolve().with_name("server.py")
        env = os.environ.copy()
        env["HTTP_PORT"] = str(self.port)
        env["HTTP_HOST"] = self.host
        env["BASE_URL"] = self.upstream_url
        if self.api_key:
            env["API_KEY"] = self.api_key

        try:
            logger.info("启动当前项目内置 REST 服务: %s", server_script)
            self._process = subprocess.Popen(
                [sys.executable, str(server_script)],
                cwd=str(server_script.parent),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            if not wait:
                return True

            started_at = time.time()
            while time.time() - started_at < timeout:
                if self.is_running:
                    logger.info("Qwen TTS REST 服务启动成功: %s", self.base_url)
                    return True

                if self._process and self._process.poll() is not None:
                    stdout, stderr = self._process.communicate()
                    logger.error(
                        "服务进程提前退出。stdout=%s stderr=%s",
                        stdout.decode("utf-8", errors="ignore"),
                        stderr.decode("utf-8", errors="ignore"),
                    )
                    return False

                time.sleep(0.5)

            logger.error("服务启动超时 (%ss)", timeout)
            return False
        except Exception as exc:
            logger.error("启动服务失败: %s", exc, exc_info=True)
            return False

    def stop(self) -> bool:
        """停止由当前实例拉起的本地 REST 服务。"""
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
                logger.info("Qwen TTS REST 服务已停止")
                return True
            except subprocess.TimeoutExpired:
                self._process.kill()
                logger.warning("Qwen TTS REST 服务已强制终止")
                return True
            except Exception as exc:
                logger.error("停止服务失败: %s", exc, exc_info=True)
                return False
        return True

    def fetch_models(self) -> bool:
        """从当前项目内置 REST 服务获取音色和语言列表。"""
        try:
            resp = requests.get(f"{self.base_url}/v1/models", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            self._voices = data.get("voices", {}) or {}
            self._languages = data.get("languages", {}) or {}
            logger.info("获取到 %s 个音色, %s 种语言", len(self._voices), len(self._languages))
            return True
        except Exception as exc:
            logger.error("获取模型列表失败: %s", exc)
            return False

    def get_voices(self, force_refresh: bool = False) -> List[VoiceInfo]:
        if force_refresh or not self._voices:
            if not self.fetch_models():
                return []
        return [VoiceInfo.from_api(vid, name) for vid, name in self._voices.items()]

    def get_languages(self, force_refresh: bool = False) -> Dict[str, str]:
        if force_refresh or not self._languages:
            if not self.fetch_models():
                return {}
        return self._languages.copy()

    def _get_default_voice(self) -> str:
        if not self._voices:
            return "vivian"

        for voice_id, display_name in self._voices.items():
            if "vivian" in voice_id.lower() or "十三" in str(display_name):
                return voice_id
        return next(iter(self._voices.keys()))

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 120,
    ) -> TTSResult:
        """通过本地 REST 服务合成语音。"""
        if not self.is_running:
            return TTSResult(success=False, error_message="服务未运行，请先调用 start()")

        if not text or not text.strip():
            return TTSResult(success=False, error_message="文本不能为空")

        if not self._voices:
            self.fetch_models()

        payload = {
            "input": text.strip(),
            "voice": voice or self._get_default_voice(),
            "language": language or DEFAULT_LANGUAGE_ID,
        }
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            resp = requests.post(
                self.api_endpoint,
                json=payload,
                headers=headers,
                timeout=timeout,
                stream=True,
            )
            resp.raise_for_status()
            audio_data = b"".join(resp.iter_content(chunk_size=8192))
            voice_id = resp.headers.get("X-Voice-Id", payload["voice"])
            language_id = resp.headers.get("X-Language-Id", payload["language"])
            content_type = resp.headers.get("Content-Type", "audio/wav")

            return TTSResult(
                success=True,
                audio_data=audio_data,
                content_type=content_type,
                voice_id=voice_id,
                language_id=language_id,
            )
        except requests.exceptions.RequestException as exc:
            logger.error("请求本地 REST 服务失败: %s", exc)
            return TTSResult(success=False, error_message=f"请求失败: {exc}")
        except Exception as exc:
            logger.error("合成失败: %s", exc, exc_info=True)
            return TTSResult(success=False, error_message=f"合成失败: {exc}")


class QwenTTSSkill:
    """Claude Skill 接口。"""

    def __init__(
        self,
        port: int = 8825,
        host: Optional[str] = None,
        api_key: Optional[str] = None,
        auto_start: bool = True,
        upstream_url: Optional[str] = None,
    ):
        self.service = QwenTTSService(
            host=host,
            port=port,
            upstream_url=upstream_url,
            api_key=api_key,
        )
        self.backend = QwenTTSBackend(
            upstream_url=upstream_url,
            api_key=api_key,
        )
        self.api_key = api_key
        self.auto_start = auto_start
        self._auto_started = False

    @property
    def host(self) -> str:
        return self.service.host

    @property
    def port(self) -> int:
        return self.service.port

    @property
    def is_running(self) -> bool:
        return self.service.is_running

    def start_service(self, wait: bool = True, timeout: int = 30) -> bool:
        self._auto_started = True
        return self.service.start(wait=wait, timeout=timeout)

    def stop_service(self) -> bool:
        return self.service.stop()

    def ensure_running(self) -> bool:
        if self.auto_start:
            return self.backend.refresh_catalog(force=False)
        return bool(self.backend.voices or self.backend.languages)

    def get_voices(self, force_refresh: bool = False) -> Dict[str, str]:
        self.backend.refresh_catalog(force=force_refresh)
        return self.backend.voices

    def get_languages(self, force_refresh: bool = False) -> Dict[str, str]:
        self.backend.refresh_catalog(force=force_refresh)
        return self.backend.languages

    def list_voices(self) -> List[Dict[str, str]]:
        voices = self.get_voices(force_refresh=False)
        return [{"id": voice_id, "name": name} for voice_id, name in voices.items()]

    def list_languages(self) -> Dict[str, str]:
        return self.get_languages(force_refresh=False)

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        output_path: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        self.ensure_running()
        result = self.backend.synthesize(text, voice, language)
        return _backend_result_to_response(result, output_path)

    def quick_say(
        self,
        text: str,
        voice: Optional[str] = None,
        output_path: Optional[str] = None,
    ) -> Optional[str]:
        self.ensure_running()
        return _backend_quick_say(self.backend, text, voice, output_path)

    def get_api_info(self) -> Dict[str, Any]:
        return {
            "endpoint": self.service.api_endpoint,
            "running": self.service.is_running,
            "base_url": self.service.base_url,
            "upstream": self.backend.upstream_url,
            "backend": "internal-gradio-adapter",
            "independent": True,
            "python_api_mode": "direct-backend",
            "rest_mode": "optional",
        }

    def __enter__(self):
        self.ensure_running()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._auto_started and self.service.is_running:
            self.stop_service()
        return False


_service_instance: Optional[QwenTTSService] = None


def create_backend(
    upstream_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> QwenTTSBackend:
    """创建一个直接调用上游的 backend 实例。"""
    return QwenTTSBackend(upstream_url=upstream_url, api_key=api_key)



def _backend_result_to_response(
    result: TTSResult,
    output_path: Optional[str] = None,
) -> Dict[str, Any]:
    response: Dict[str, Any] = {
        "success": result.success,
        "voice_id": result.voice_id,
        "language_id": result.language_id,
        "error": result.error_message,
        "audio_path": None,
    }

    if output_path and result.success:
        if result.save_to_file(output_path):
            response["audio_path"] = output_path
    elif result.success and result.audio_data is not None:
        response["audio_base64"] = base64.b64encode(result.audio_data).decode("utf-8")

    return response



def _backend_quick_say(
    backend: QwenTTSBackend,
    text: str,
    voice: Optional[str] = None,
    output_path: Optional[str] = None,
) -> Optional[str]:
    backend.refresh_catalog(force=False)
    result = backend.synthesize(text, voice, DEFAULT_LANGUAGE_ID)
    if not result.success:
        return None

    if output_path:
        return output_path if result.save_to_file(output_path) else None

    temp_file = tempfile.NamedTemporaryFile(prefix="qwen-tts-", suffix=".wav", delete=False)
    temp_file.close()
    return temp_file.name if result.save_to_file(temp_file.name) else None



def get_service(port: int = 8825) -> QwenTTSService:
    global _service_instance
    if _service_instance is None or _service_instance.port != port:
        _service_instance = QwenTTSService(port=port)
    return _service_instance



def ensure_service(port: int = 8825) -> bool:
    service = get_service(port)
    if not service.is_running:
        return service.start()
    return True



def skill_start(port: int = 8825, auto_start: bool = True) -> QwenTTSSkill:
    return QwenTTSSkill(port=port, auto_start=auto_start)



def skill_say(
    text: str,
    voice: Optional[str] = None,
    port: int = 8825,
    output_path: Optional[str] = None,
) -> Optional[str]:
    backend = create_backend()
    return _backend_quick_say(backend, text, voice, output_path)



def skill_voices(port: int = 8825) -> List[Dict[str, str]]:
    backend = create_backend()
    backend.refresh_catalog(force=False)
    return [{"id": voice_id, "name": name} for voice_id, name in backend.voices.items()]



def skill_languages(port: int = 8825) -> Dict[str, str]:
    backend = create_backend()
    backend.refresh_catalog(force=False)
    return backend.languages



def tts(
    text: str,
    voice: Optional[str] = None,
    language: Optional[str] = None,
    output_path: Optional[str] = None,
    port: int = 8825,
) -> str:
    backend = create_backend()
    backend.refresh_catalog(force=False)
    result = backend.synthesize(text, voice, language)
    response = _backend_result_to_response(result, output_path)
    if response["success"]:
        return response.get("audio_path") or "合成成功"
    return f"失败: {response['error']}"


# 向后兼容别名
QwenTTS = QwenTTSSkill


def create_app(
    upstream_url: Optional[str] = None,
    api_key: Optional[str] = None,
):
    """创建 FastAPI 应用。"""
    missing_dependencies = get_missing_rest_dependencies()
    if missing_dependencies:
        raise RuntimeError(build_missing_rest_dependencies_message(missing_dependencies))

    from contextlib import asynccontextmanager

    from fastapi import FastAPI, Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse

    backend = QwenTTSBackend(upstream_url=upstream_url, api_key=api_key)
    service_api_key = api_key or os.getenv("API_KEY")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("启动内置 Qwen TTS FastAPI 服务...")
        backend.refresh_catalog(force=True)
        yield
        logger.info("内置 Qwen TTS FastAPI 服务已关闭")

    app = FastAPI(
        title="Qwen TTS API",
        description="OpenAI-compatible Text-to-Speech API backed by the internal qwen-tts-skill adapter",
        version="0.2.1",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _check_auth(authorization: Optional[str]) -> None:
        if not service_api_key:
            return
        if authorization not in {service_api_key, f"Bearer {service_api_key}"}:
            raise HTTPException(status_code=401, detail="Unauthorized")

    @app.get("/")
    async def index() -> Dict[str, Any]:
        return {
            "name": "Qwen TTS API",
            "version": "0.2.1",
            "backend": "internal-gradio-adapter",
            "upstream": backend.upstream_url,
            "independent": True,
        }

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "voices_cached": len(backend.voices),
            "languages_cached": len(backend.languages),
            "upstream": backend.upstream_url,
        }

    @app.get("/v1/models")
    async def get_models() -> Dict[str, Any]:
        return backend.get_models_payload(auth_required=bool(service_api_key))

    @app.get("/v1/voices")
    async def list_voices() -> Dict[str, Any]:
        if not backend.voices:
            backend.refresh_catalog()
        return {
            "voices": [{"id": voice_id, "name": name} for voice_id, name in backend.voices.items()]
        }

    @app.post("/v1/audio/speech")
    async def create_speech(
        request: SpeechRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        _check_auth(authorization)

        result = backend.synthesize(
            text=request.input,
            voice=request.voice,
            language=request.language,
        )
        if not result.success or result.audio_data is None:
            raise HTTPException(status_code=502, detail=result.error_message or "Failed to generate audio")

        headers = {
            "Content-Disposition": 'inline; filename="speech.wav"',
            "X-Voice-Id": result.voice_id or "default",
            "X-Language-Id": result.language_id or DEFAULT_LANGUAGE_ID,
        }
        return StreamingResponse(
            io.BytesIO(result.audio_data),
            media_type=result.content_type or "audio/wav",
            headers=headers,
        )

    return app


def start_server(
    host: str = "0.0.0.0",
    port: int = 8825,
    upstream_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> None:
    missing_dependencies = get_missing_rest_dependencies()
    if missing_dependencies:
        raise RuntimeError(build_missing_rest_dependencies_message(missing_dependencies))

    import uvicorn

    app = create_app(upstream_url=upstream_url, api_key=api_key)
    uvicorn.run(app, host=host, port=port)


def main() -> None:
    parser = argparse.ArgumentParser(description="Qwen TTS Skill")
    parser.add_argument("--serve", action="store_true", help="以前台方式运行内置 FastAPI 服务")
    parser.add_argument("--say", type=str, help="合成语音文本")
    parser.add_argument("--voice", type=str, help="音色ID")
    parser.add_argument("--language", type=str, help="语言ID")
    parser.add_argument("--list-voices", action="store_true", help="列出可用音色")
    parser.add_argument("--list-languages", action="store_true", help="列出可用语言")
    parser.add_argument("--output", type=str, help="输出文件路径")
    parser.add_argument("--port", type=int, default=8825, help="REST 服务端口（仅 `--serve` 时使用）")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="REST 服务主机（仅 `--serve` 时使用）")
    parser.add_argument("--base-url", type=str, default=os.getenv("BASE_URL", DEFAULT_UPSTREAM_URL), help="上游 Gradio 地址")
    args = parser.parse_args()

    if args.serve:
        start_server(
            host=args.host,
            port=args.port,
            upstream_url=args.base_url,
            api_key=os.getenv("API_KEY"),
        )
        return

    if args.say:
        backend = create_backend(upstream_url=args.base_url, api_key=os.getenv("API_KEY"))
        result = _backend_quick_say(backend, args.say, args.voice, args.output)
        print(f"音频已保存到: {result}" if result else "合成失败")
    elif args.list_voices:
        backend = create_backend(upstream_url=args.base_url, api_key=os.getenv("API_KEY"))
        backend.refresh_catalog(force=False)
        voices = [{"id": voice_id, "name": name} for voice_id, name in backend.voices.items()]
        print("可用音色:")
        for voice in voices:
            print(f"  - {voice['id']}: {voice['name']}")
    elif args.list_languages:
        backend = create_backend(upstream_url=args.base_url, api_key=os.getenv("API_KEY"))
        backend.refresh_catalog(force=False)
        languages = backend.languages
        print("可用语言:")
        for language_id, language_name in languages.items():
            print(f"  - {language_id}: {language_name}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
