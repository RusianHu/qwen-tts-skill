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
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---- 核心依赖预检 ----
# skill 分发到全新环境时依赖通常尚未安装。若不加拦截，用户只会看到裸的
# `ModuleNotFoundError` traceback，无从得知该装什么。
# 仅在作为脚本运行时拦截，测试环境仍可正常 import 本模块。
if __name__ == "__main__":
    import importlib.util as _importlib_util

    _missing_core = [
        package_spec
        for module_name, package_spec in (
            ("requests", "requests>=2.31.0"),
            ("gradio_client", "gradio_client>=2.0.0"),
        )
        if _importlib_util.find_spec(module_name) is None
    ]
    if _missing_core:
        print(
            "缺少运行依赖: " + ", ".join(_missing_core) + "\n"
            "请在当前 skill 根目录执行：\n"
            "    pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt\n"
            "（skill 不会在运行时自动安装依赖，需手动执行一次。）"
        )
        sys.exit(1)

import requests
from gradio_client import Client

# pydantic 仅在 REST 模式下用于定义请求体模型，不在核心合成链路上。
# 这里延迟导入，使核心能力（--say / --list-voices / --list-languages）
# 只依赖 requests 与 gradio_client，与 requirements 的分层意图一致。
try:
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - 仅在未安装 pydantic 时触发
    BaseModel = None  # type: ignore[assignment]

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# 上游 Gradio 服务地址。
# 原地址 `https://qwen-qwen3-tts-demo.ms.show` 已于 2026 年废弃（HTTP 403，
# 提示改走需要 ModelScope token 的 api-inference 地址），故切换到
# 参数签名完全兼容（/tts_interface + text/voice_display/language_display）
# 且免鉴权的 HuggingFace Space。
# 版本号唯一来源。pyproject.toml 中的 version 必须与之保持一致
# （tests/test_skill.py 中有用例会校验两者不漂移）。
__version__ = "0.3.1"
SKILL_VERSION = __version__

DEFAULT_UPSTREAM_URL = "https://qwen-qwen3-tts-demo.hf.space"
# 保留旧地址常量，便于诊断与回滚。
LEGACY_UPSTREAM_URL = "https://qwen-qwen3-tts-demo.ms.show"
DEFAULT_API_NAME = "/tts_interface"
DEFAULT_MODEL_ID = "qwen-tts"
DEFAULT_LANGUAGE_ID = "auto"
DEFAULT_LANGUAGE_NAME = "Auto / 自动"
DEFAULT_VOICE_NAME = "Vivian / 十三"

# 上游语言 display 名为 `English / 英文` 这样的形式，规范化后是 `english` 全拼，
# 而调用方（含 SKILL.md 文档）习惯传 `zh` / `en` 这类 ISO 639-1 两字母代码。
# 没有这张别名表时，传 `zh` 会静默回退成 auto —— 不报错但语言参数不生效。
LANGUAGE_ALIASES: Dict[str, str] = {
    "auto": "auto",
    "zh": "chinese", "cn": "chinese", "zh-cn": "chinese", "zh-hans": "chinese",
    "zh-tw": "chinese", "zh-hk": "chinese", "chinese": "chinese", "中文": "chinese",
    "en": "english", "en-us": "english", "en-gb": "english", "english": "english",
    "ja": "japanese", "jp": "japanese", "japanese": "japanese",
    "ko": "korean", "kr": "korean", "korean": "korean",
    "de": "german", "ger": "german", "german": "german",
    "fr": "french", "fre": "french", "french": "french",
    "ru": "russian", "rus": "russian", "russian": "russian",
    "pt": "portuguese", "por": "portuguese", "portuguese": "portuguese",
    "es": "spanish", "spa": "spanish", "spanish": "spanish",
    "it": "italian", "ita": "italian", "italian": "italian",
}
# ---- 凭据边界 ----
# 本地 REST 服务密钥与远端上游凭据属于**不同信任边界**，必须分开配置。
# 历史实现把同一个 API_KEY 既用于保护本机 127.0.0.1 服务、又作为
# `Authorization: Bearer` 发给第三方上游，属于 secret-boundary violation：
# 用户为保护本地端口设的密码会泄露给远端。默认上游本身免鉴权，
# 本地密钥没有任何理由离开本机。
ENV_UPSTREAM_API_KEY = "QWEN_TTS_UPSTREAM_API_KEY"
ENV_REST_API_KEY = "QWEN_TTS_REST_API_KEY"
ENV_LEGACY_API_KEY = "API_KEY"

# catalog 刷新失败后的静默期（秒）：期间不再重复探测上游，
# 防止上游故障时一次用户请求被 resolver 放大成大量连接/超时。
CATALOG_FAILURE_TTL = 30.0

# 核心依赖：任何调用方式（含 --say / --list-voices）都必须具备。
CORE_REQUIRED_PACKAGES = {
    "requests": "requests>=2.31.0",
    "gradio_client": "gradio_client>=2.0.0",
}
# 启动可选 REST 服务时的完整依赖集合（核心依赖 + Web 框架）。
REST_REQUIRED_PACKAGES = {
    "fastapi": "fastapi>=0.100.0",
    "uvicorn": "uvicorn>=0.20.0",
    "pydantic": "pydantic>=2.0.0",
    **CORE_REQUIRED_PACKAGES,
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


def get_missing_core_dependencies() -> List[str]:
    """返回运行核心功能（语音合成/枚举查询）所需但缺失的依赖包列表。"""
    missing: List[str] = []

    for module_name, package_spec in CORE_REQUIRED_PACKAGES.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_spec)

    return missing


def build_missing_core_dependencies_message(missing_dependencies: List[str]) -> str:
    """构造缺失核心依赖时的统一错误消息。

    skill 分发到一个全新环境时，依赖往往尚未安装。若不加拦截，用户只会看到
    裸的 `ModuleNotFoundError` traceback，无从得知该装什么。
    """
    if not missing_dependencies:
        return ""

    return (
        "缺少运行依赖: " + ", ".join(missing_dependencies) + "。\n"
        "请在当前 skill 根目录执行：\n"
        "    pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt\n"
        "（skill 不会在运行时自动安装依赖，需手动执行一次。）"
    )


def resolve_rest_api_key(explicit: Optional[str] = None) -> Optional[str]:
    """解析**本地 REST 服务**的鉴权密钥。

    优先级：显式传入 > `QWEN_TTS_REST_API_KEY` > `API_KEY`（legacy）。

    `API_KEY` 仅为兼容旧配置保留，语义已收敛为「本地 REST 密钥」，
    **绝不**作为 Bearer token 发送给远端上游（见 `resolve_upstream_api_key`）。
    """
    if explicit:
        return explicit

    value = os.getenv(ENV_REST_API_KEY)
    if value:
        return value

    legacy = os.getenv(ENV_LEGACY_API_KEY)
    if legacy:
        logger.warning(
            "环境变量 %s 已废弃：它现在只用于保护本地 REST 服务，不再发送给远端上游。"
            "请改用 %s（本地 REST）与 %s（上游凭据）以明确凭据边界。",
            ENV_LEGACY_API_KEY, ENV_REST_API_KEY, ENV_UPSTREAM_API_KEY,
        )
        return legacy

    return None


def resolve_upstream_api_key(explicit: Optional[str] = None) -> Optional[str]:
    """解析**远端上游**凭据。

    只接受显式传入或 `QWEN_TTS_UPSTREAM_API_KEY`。
    刻意**不**回退到 `API_KEY` —— 那是本地 REST 密钥，不得离开本机。
    默认上游（HuggingFace Space）免鉴权，通常无需配置。
    """
    return explicit or os.getenv(ENV_UPSTREAM_API_KEY)


def parse_env_int(
    name: str,
    default: int,
    minimum: int = 1,
    maximum: Optional[int] = None,
) -> int:
    """解析整数环境变量，带范围校验。

    用户填入非法值（非数字/越界）时不应在构造或 import 阶段直接抛异常：
    回退默认值并给出可操作的告警。
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        logger.warning(
            "环境变量 %s=%r 不是有效整数，已回退为默认值 %s", name, raw, default,
        )
        return default
    if value < minimum or (maximum is not None and value > maximum):
        bound = f"[{minimum}, {maximum}]" if maximum is not None else f">= {minimum}"
        logger.warning(
            "环境变量 %s=%s 超出允许范围 %s，已回退为默认值 %s", name, value, bound, default,
        )
        return default
    return value


def parse_env_float(name: str, default: float, minimum: float = 0.0) -> float:
    """解析浮点环境变量，带下界校验；非法值回退默认并告警。"""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        logger.warning(
            "环境变量 %s=%r 不是有效数字，已回退为默认值 %s", name, raw, default,
        )
        return default
    if value < minimum:
        logger.warning(
            "环境变量 %s=%s 低于允许下界 %s，已回退为默认值 %s",
            name, value, minimum, default,
        )
        return default
    return value


def parse_env_str(name: str, default: str) -> str:
    """解析字符串环境变量，空值回退默认。"""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


if BaseModel is not None:

    class SpeechRequest(BaseModel):
        """REST 语音合成请求体（仅在启用 REST 服务时可用）。"""

        input: str
        voice: Optional[str] = None
        language: Optional[str] = DEFAULT_LANGUAGE_ID

else:  # pragma: no cover - 仅在未安装 pydantic 时触发
    SpeechRequest = None  # type: ignore[assignment]


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
        upstream_api_key: Optional[str] = None,
    ):
        self.upstream_url = upstream_url or os.getenv("BASE_URL", DEFAULT_UPSTREAM_URL)
        self.api_name = api_name
        # 只认上游专用凭据，绝不读取 API_KEY（那是本地 REST 密钥）
        self.upstream_api_key = resolve_upstream_api_key(upstream_api_key)
        # 上游重试策略（托管型 Space 偶发抖动），可用环境变量覆盖
        self.max_attempts = parse_env_int("QWEN_TTS_MAX_ATTEMPTS", 3, minimum=1)
        self.retry_delay = parse_env_float("QWEN_TTS_RETRY_DELAY", 2.0, minimum=0.0)
        self._voices: Dict[str, str] = {}
        self._languages: Dict[str, str] = {}
        self._voice_index: Dict[str, str] = {}
        self._catalog_failed_at: Optional[float] = None
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
        """创建上游客户端。

        仅当显式配置了上游凭据（参数或 `QWEN_TTS_UPSTREAM_API_KEY`）时才携带
        Authorization 头。本地 REST 密钥不会出现在发往远端的请求里。
        """
        client_kwargs: Dict[str, Any] = {"verbose": False}
        if self.upstream_api_key:
            client_kwargs["headers"] = {
                "Authorization": f"Bearer {self.upstream_api_key}"
            }
        # verbose=False：抑制 gradio_client 往 stdout 打印的 "Loaded as API: ..."，
        # 否则 CLI 输出会被污染，干扰 agent 解析 --list-voices 等命令的结果。
        return Client(self.upstream_url, **client_kwargs)

    @staticmethod
    def _normalize_option_id(option_label: str) -> str:
        value = str(option_label or "").strip().lower()
        if not value:
            return ""
        return value.split("/")[0].strip()

    @staticmethod
    def _canonical_key(value: str) -> str:
        """把音色/语言名压成不含空格、连字符、下划线的比对键。

        上游存在 `Ono Anna / 日语-小野杏`、`Radio Gol / ...`、`Eldric Sage / ...`
        这类带空格的 ID，调用方写 `ono-anna` 或 `onoanna` 都应能命中。
        """
        value = str(value or "").strip().lower()
        if not value:
            return ""
        value = value.split("/")[0].strip()
        return re.sub(r"[\s_\-]+", "", value)

    def _catalog_is_stale(self) -> bool:
        """catalog 缓存是否缺失/不完整。"""
        return not (self._voices and self._languages)

    def _catalog_in_backoff(self) -> bool:
        """上一次刷新失败后是否仍处于静默期。"""
        if self._catalog_failed_at is None:
            return False
        return (time.time() - self._catalog_failed_at) < CATALOG_FAILURE_TTL

    def ensure_catalog(self, force: bool = False) -> bool:
        """确保 catalog 可用；失败带 TTL 退避，避免故障被放大。

        上游不可用时，若每次 resolver 都触发刷新，一次用户请求会被放大成
        大量远端连接/超时。这里统一收敛：一次调用内最多刷新一次，
        且刷新失败后 `CATALOG_FAILURE_TTL` 秒内不再重复探测。
        """
        if not force and not self._catalog_is_stale():
            return True
        if not force and self._catalog_in_backoff():
            logger.debug("catalog 上次刷新失败，处于 %ss 退避期，跳过探测", CATALOG_FAILURE_TTL)
            return False
        return self.refresh_catalog(force=force)

    def refresh_catalog(self, force: bool = False) -> bool:
        """刷新远端音色 / 语言枚举缓存。"""
        if not force and self._voices and self._languages:
            return True

        voices: Dict[str, str] = {}
        languages: Dict[str, str] = {}
        client: Optional[Client] = None

        try:
            # 注意：创建 Client 会立刻请求上游 /config，上游不可达时这里就抛异常。
            # 早期实现把这一行放在 try 之外，异常直接冒泡，导致 CLI 崩溃、
            # FastAPI lifespan 失败（服务起不来）。必须纳入 try。
            client = self._create_client()
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
            self._catalog_failed_at = time.time()
            return False
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

        if not voices or not languages:
            # 「没有异常」不等于「拿到有效 catalog」。空结果不能覆盖有效缓存，
            # 否则上游短暂抽风会清空本地已知的音色/语言。
            logger.warning(
                "上游返回空 catalog（voices=%d, languages=%d），保留旧缓存",
                len(voices), len(languages),
            )
            self._catalog_failed_at = time.time()
            return False

        self._catalog_failed_at = None
        self._voices = voices
        self._languages = languages
        self._voice_index = {
            self._canonical_key(voice_id): voice_id for voice_id in voices
        }

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
        # 纯解析：只读缓存，不触发网络。catalog 加载由入口的 ensure_catalog 统一负责。
        voice_id = (requested_voice or "").strip().lower()
        if voice_id and voice_id in self._voices:
            return voice_id

        # 容错匹配：`ono-anna` / `onoanna` / `Ono Anna` 都能命中 `ono anna`
        canonical = self._canonical_key(voice_id)
        if canonical:
            if not self._voice_index and self._voices:
                self._voice_index = {
                    self._canonical_key(vid): vid for vid in self._voices
                }
            if canonical in self._voice_index:
                return self._voice_index[canonical]

        return self._default_voice_id or self._pick_default_voice_id()

    def _resolve_language_id(self, requested_language: Optional[str]) -> str:
        # 纯解析：只读缓存，不触发网络
        language_id = (requested_language or DEFAULT_LANGUAGE_ID).strip().lower()
        if language_id in self._languages:
            return language_id

        # 两字母代码（zh/en/ja…）映射到上游的 english/chinese/… 全拼 ID
        aliased = LANGUAGE_ALIASES.get(language_id)
        if aliased and aliased in self._languages:
            return aliased

        # 兜底：忽略大小写与分隔符差异再比一次
        canonical = self._canonical_key(language_id)
        for lang_id in self._languages:
            if self._canonical_key(lang_id) == canonical:
                return lang_id

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

    def get_models_payload(self, auth_required: bool = False) -> Dict[str, Any]:
        """组装 /v1/models 响应。

        `auth_required` 描述的是**本地 REST 服务**是否要求鉴权，由 `create_app`
        传入；backend 自身不持有本地 REST 密钥。
        """
        self.ensure_catalog()

        return {
            "data": [{"id": DEFAULT_MODEL_ID}],
            "voices": self.voices,
            "languages": self.languages,
            "default_voice": self._resolve_voice_id(None),
            "default_language": self._resolve_language_id(None),
            "auth_required": auth_required,
            "backend": "internal-gradio-adapter",
            "upstream": self.upstream_url,
        }

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        max_attempts: Optional[int] = None,
    ) -> TTSResult:
        """直接调用远端 Gradio 接口生成语音。

        托管型上游（HuggingFace Space）存在偶发失败：实测 49 个音色中有 1 个
        首次调用报 AppError，重试即成功；也可能出现 SSL 握手超时。因此这里
        默认带重试，避免把上游抖动直接暴露成调用失败。
        """
        if not text or not text.strip():
            return TTSResult(success=False, error_message="文本不能为空")

        attempts = max_attempts or self.max_attempts
        attempts = max(1, int(attempts))

        last_result: Optional[TTSResult] = None
        for attempt in range(1, attempts + 1):
            result = self._synthesize_once(text, voice, language)
            if result.success:
                return result

            last_result = result
            if attempt < attempts:
                logger.warning(
                    "第 %s/%s 次合成失败，%ss 后重试: %s",
                    attempt, attempts, self.retry_delay, result.error_message,
                )
                time.sleep(self.retry_delay * attempt)

        return last_result or TTSResult(success=False, error_message="合成失败")

    def _synthesize_once(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
    ) -> TTSResult:
        """单次合成尝试（不含重试）。"""
        # 一次尝试只做一次 catalog 探测（带 TTL 退避），resolver 均为纯解析
        self.ensure_catalog()

        resolved_voice_id = self._resolve_voice_id(voice)
        resolved_language_id = self._resolve_language_id(language)
        resolved_voice_name = self._resolve_voice_name(resolved_voice_id)
        resolved_language_name = self._resolve_language_name(resolved_language_id)

        client: Optional[Client] = None
        audio_path: Optional[str] = None

        try:
            # 与 refresh_catalog 同理：Client 构造会立即发起网络请求，
            # 上游超时/不可达时这里就会抛异常，必须纳入 try 才能优雅返回
            # success=False，否则调用方会直接崩。
            client = self._create_client()
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
            if client is not None:
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
        self.host = host or parse_env_str("HTTP_HOST", self.DEFAULT_HOST)
        self.port = port or parse_env_int("HTTP_PORT", self.DEFAULT_PORT, minimum=1, maximum=65535)
        self.upstream_url = upstream_url or os.getenv("BASE_URL", DEFAULT_UPSTREAM_URL)
        # 本地 REST 密钥（仅用于保护 127.0.0.1 服务，不发给上游）
        self.api_key = resolve_rest_api_key(api_key)
        # 上游凭据单独持有，仅在启动子进程时透传给 backend
        self.upstream_api_key = resolve_upstream_api_key()
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
            # 子进程里它只作为本地 REST 密钥使用
            env[ENV_REST_API_KEY] = self.api_key
        if self.upstream_api_key:
            env[ENV_UPSTREAM_API_KEY] = self.upstream_api_key
        # 避免把父进程里可能存在的 legacy API_KEY 泄漏进子进程，
        # 保证子进程的凭据语义与本次显式配置完全一致。
        env.pop(ENV_LEGACY_API_KEY, None)

        try:
            logger.info("启动当前项目内置 REST 服务: %s", server_script)
            # 不使用 stdout/stderr PIPE：正常运行期间没有消费者持续读取，
            # 服务日志写满 pipe buffer 后会阻塞子进程。改为 DEVNULL 丢弃，
            # 需要排错时用户可自行前台运行 scripts/server.py。
            self._process = subprocess.Popen(
                [sys.executable, str(server_script)],
                cwd=str(server_script.parent),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
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
                    logger.error(
                        "服务进程提前退出（退出码 %s）。"
                        "请前台运行 scripts/server.py 查看完整日志。",
                        self._process.returncode,
                    )
                    self._cleanup_process()
                    return False

                time.sleep(0.5)

            # 超时：必须清理子进程，否则会残留一个占用端口的服务进程
            logger.error("服务启动超时 (%ss)，正在清理子进程", timeout)
            self._cleanup_process()
            return False
        except Exception as exc:
            logger.error("启动服务失败: %s", exc, exc_info=True)
            self._cleanup_process()
            return False

    def _cleanup_process(self) -> None:
        """统一的子进程清理：terminate -> wait -> kill -> wait。

        保证 start() 的任何失败/超时路径都不会残留服务进程。
        """
        process = self._process
        if process is None:
            return

        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        except Exception as exc:  # pragma: no cover - 清理失败不应抛出
            logger.warning("清理服务子进程时出错: %s", exc)
        finally:
            self._process = None

    def stop(self) -> bool:
        """停止由当前实例拉起的本地 REST 服务。"""
        if self._process is None:
            return True

        if self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
                logger.info("Qwen TTS REST 服务已停止")
                self._process = None
                return True
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=5)
                logger.warning("Qwen TTS REST 服务已强制终止")
                self._process = None
                return True
            except Exception as exc:
                logger.error("停止服务失败: %s", exc, exc_info=True)
                return False

        self._process = None
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
        # 优先使用显式传入的 key，否则自动使用实例自身的 REST key，
        # 避免「服务启用了鉴权，但自己调用自己却 401」。
        request_api_key = api_key or self.api_key
        if request_api_key:
            headers["Authorization"] = f"Bearer {request_api_key}"

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
        upstream_api_key: Optional[str] = None,
    ):
        # api_key 只用于本地 REST 服务；upstream_api_key 才发给远端。
        self.service = QwenTTSService(
            host=host,
            port=port,
            upstream_url=upstream_url,
            api_key=api_key,
        )
        self.backend = QwenTTSBackend(
            upstream_url=upstream_url,
            upstream_api_key=upstream_api_key,
        )
        self.api_key = resolve_rest_api_key(api_key)
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
    ) -> Dict[str, Any]:
        """合成语音（直连上游，不经本地 REST）。

        注：此前这里存在 `api_key` 参数但从未被使用 —— 合成走的是 backend 直连，
        不涉及本地 REST 鉴权。保留一个无效参数会误导调用方，故移除。
        """
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
    upstream_api_key: Optional[str] = None,
) -> QwenTTSBackend:
    """创建一个直接调用上游的 backend 实例。"""
    return QwenTTSBackend(upstream_url=upstream_url, upstream_api_key=upstream_api_key)



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
    output_path: Optional[str] = None,
) -> Optional[str]:
    """快速合成（直连上游；`port` 参数已移除——直连模式不涉及本地 REST）。"""
    backend = create_backend()
    return _backend_quick_say(backend, text, voice, output_path)


def skill_voices() -> List[Dict[str, str]]:
    backend = create_backend()
    backend.ensure_catalog()
    return [{"id": voice_id, "name": name} for voice_id, name in backend.voices.items()]


def skill_languages() -> Dict[str, str]:
    backend = create_backend()
    backend.ensure_catalog()
    return backend.languages



def tts(
    text: str,
    voice: Optional[str] = None,
    language: Optional[str] = None,
    output_path: Optional[str] = None,
) -> str:
    """便捷合成：给定 `output_path` 时返回文件路径，否则返回 base64 数据。

    历史实现在未指定 `output_path` 时会把合成的 base64 音频丢弃、只返回
    「合成成功」，成功却拿不到任何音频数据。现改为返回 base64（data URI 前缀
    便于前端直接使用），调用方可自行解码或落盘。
    """
    backend = create_backend()
    backend.ensure_catalog()
    result = backend.synthesize(text, voice, language)
    response = _backend_result_to_response(result, output_path)
    if not response["success"]:
        return f"失败: {response['error']}"
    if response.get("audio_path"):
        return str(response["audio_path"])
    base64_audio = response.get("audio_base64")
    if base64_audio:
        return f"data:audio/wav;base64,{base64_audio}"
    return "合成成功（但未生成可返回的音频数据）"


# 向后兼容别名
QwenTTS = QwenTTSSkill


def create_app(
    upstream_url: Optional[str] = None,
    api_key: Optional[str] = None,
    upstream_api_key: Optional[str] = None,
):
    """创建 FastAPI 应用。

    - `api_key`：保护**本地 REST 服务**的密钥，绝不会发送给远端上游
    - `upstream_api_key`：仅在远端上游需要鉴权时才配置
    """
    missing_dependencies = get_missing_rest_dependencies()
    if missing_dependencies:
        raise RuntimeError(build_missing_rest_dependencies_message(missing_dependencies))

    from contextlib import asynccontextmanager

    from fastapi import FastAPI, Header, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import StreamingResponse

    backend = QwenTTSBackend(upstream_url=upstream_url, upstream_api_key=upstream_api_key)
    service_api_key = resolve_rest_api_key(api_key)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("启动内置 Qwen TTS FastAPI 服务...")
        backend.refresh_catalog(force=True)
        yield
        logger.info("内置 Qwen TTS FastAPI 服务已关闭")

    app = FastAPI(
        title="Qwen TTS API",
        description=(
            "OpenAI-style /v1/audio/speech compatibility subset "
            "(input/voice/language, always returns WAV) backed by the "
            "internal qwen-tts-skill adapter"
        ),
        version=SKILL_VERSION,
        lifespan=lifespan,
    )

    # CORS 默认关闭：这是被 Agent 自动拉起的本地服务，不应默认对任意来源开放。
    # 确实需要浏览器跨域访问时，通过 QWEN_TTS_CORS_ORIGINS 显式开启。
    cors_origins = [
        origin.strip()
        for origin in os.getenv("QWEN_TTS_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
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
            "version": SKILL_VERSION,
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
    def create_speech(
        request: SpeechRequest,
        authorization: Optional[str] = Header(default=None),
    ):
        # 刻意声明为同步 def：backend.synthesize() 是阻塞实现（网络 I/O +
        # gradio predict + 重试 sleep），单次可达数分钟。若写成 async def，
        # 它会直接占用 event loop，导致 /health 等路由在合成期间无响应。
        # 同步 def 会让 FastAPI 自动放进线程池执行。
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
    host: str = "127.0.0.1",
    port: int = 8825,
    upstream_url: Optional[str] = None,
    api_key: Optional[str] = None,
    upstream_api_key: Optional[str] = None,
) -> None:
    """前台启动 REST 服务。

    `host` 默认只绑定本机回环地址；要暴露到局域网/公网，
    必须显式传入 `host="0.0.0.0"`。
    """
    missing_dependencies = get_missing_rest_dependencies()
    if missing_dependencies:
        raise RuntimeError(build_missing_rest_dependencies_message(missing_dependencies))

    import uvicorn

    app = create_app(
        upstream_url=upstream_url,
        api_key=api_key,
        upstream_api_key=upstream_api_key,
    )
    uvicorn.run(app, host=host, port=port)


# CLI 退出码约定（对 Agent / shell 自动化是基本的成功失败协议）：
#   0 = 成功
#   1 = 合成 / 上游 / 运行时失败
#   2 = CLI 参数错误
#   3 = 配置 / 依赖错误
EXIT_OK = 0
EXIT_RUNTIME_FAILURE = 1
EXIT_USAGE_ERROR = 2
EXIT_CONFIG_ERROR = 3


def _emit(payload: Dict[str, Any], as_json: bool) -> None:
    """统一输出：--json 模式给 agent 稳定解析，否则人类可读。"""
    if as_json:
        print(json.dumps(payload, ensure_ascii=False))
        return
    if payload.get("success") is False:
        print(f"失败: {payload.get('error')}")
        return
    if "voices" in payload:
        print("可用音色:")
        for voice in payload["voices"]:
            print(f"  - {voice['id']}: {voice['name']}")
    elif "languages" in payload:
        print("可用语言:")
        for language_id, language_name in payload["languages"].items():
            print(f"  - {language_id}: {language_name}")
    elif payload.get("path"):
        print(f"音频已保存到: {payload['path']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen TTS Skill")
    parser.add_argument("--serve", action="store_true", help="以前台方式运行内置 FastAPI 服务")
    parser.add_argument("--say", type=str, help="合成语音文本")
    parser.add_argument("--voice", type=str, help="音色ID")
    parser.add_argument("--language", type=str, help="语言ID")
    parser.add_argument("--list-voices", action="store_true", help="列出可用音色")
    parser.add_argument("--list-languages", action="store_true", help="列出可用语言")
    parser.add_argument("--output", type=str, help="输出文件路径")
    parser.add_argument(
        "--json", action="store_true",
        help="以单行 JSON 输出结果（供 Agent / 脚本稳定解析）",
    )
    parser.add_argument("--port", type=int, default=8825, help="REST 服务端口（仅 `--serve` 时使用）")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="REST 服务主机（仅 `--serve` 时使用）")
    parser.add_argument("--base-url", type=str, default=os.getenv("BASE_URL", DEFAULT_UPSTREAM_URL), help="上游 Gradio 地址")
    args = parser.parse_args()

    # 互斥参数：--say 与 --list-* 同时给是没有意义的调用
    exclusive_flags = [bool(args.say), args.list_voices, args.list_languages]
    if sum(exclusive_flags) > 1:
        parser.error("--say / --list-voices / --list-languages 只能同时使用一个")

    if args.serve:
        start_server(
            host=args.host,
            port=args.port,
            upstream_url=args.base_url,
            api_key=resolve_rest_api_key(),
            upstream_api_key=resolve_upstream_api_key(),
        )
        return EXIT_OK

    upstream_key = resolve_upstream_api_key()

    if args.say:
        backend = create_backend(upstream_url=args.base_url, upstream_api_key=upstream_key)
        result = _backend_quick_say(backend, args.say, args.voice, args.output)
        _emit({"success": bool(result), "path": result}, args.json)
        return EXIT_OK if result else EXIT_RUNTIME_FAILURE

    if args.list_voices or args.list_languages:
        backend = create_backend(upstream_url=args.base_url, upstream_api_key=upstream_key)
        if not backend.ensure_catalog():
            _emit(
                {"success": False, "error": f"无法从上游获取目录: {backend.upstream_url}"},
                args.json,
            )
            return EXIT_RUNTIME_FAILURE
        if args.list_voices:
            _emit(
                {"success": True, "voices": [{"id": v, "name": n} for v, n in backend.voices.items()]},
                args.json,
            )
        else:
            _emit({"success": True, "languages": backend.languages}, args.json)
        return EXIT_OK

    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
