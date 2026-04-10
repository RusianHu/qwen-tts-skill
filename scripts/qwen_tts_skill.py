"""
Qwen TTS Skill for Claude

将 Qwen TTS (通义千问语音合成) 转换为 OpenAI 兼容的 REST API 服务，
并提供便捷的 Python API 供 Claude 调用。
"""

import os
import sys
import time
import json
import base64
import logging
import subprocess
import requests
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
from dataclasses import dataclass
from contextlib import contextmanager

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class VoiceInfo:
    """音色信息"""
    id: str
    name: str

    @classmethod
    def from_api(cls, vid: str, name: str) -> 'VoiceInfo':
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
            with open(filepath, 'wb') as f:
                f.write(self.audio_data)
            logger.info(f"音频已保存到: {filepath}")
            return True
        except Exception as e:
            logger.error(f"保存音频失败: {e}")
            return False


class QwenTTSService:
    """Qwen TTS 服务管理器"""

    DEFAULT_PORT = 8825
    DEFAULT_HOST = "127.0.0.1"
    BASE_URL = os.getenv("BASE_URL", "https://qwen-qwen3-tts-demo.ms.show")

    def __init__(self, host: str = None, port: int = None):
        self.host = host or self.DEFAULT_HOST
        self.port = port or self.DEFAULT_PORT
        self.base_url = f"http://{self.host}:{self.port}"
        self._process: Optional[subprocess.Popen] = None
        self._voices: Dict[str, str] = {}
        self._languages: Dict[str, str] = {}

    @property
    def is_running(self) -> bool:
        """检查服务是否运行"""
        try:
            resp = requests.get(f"{self.base_url}/v1/models", timeout=2)
            return resp.status_code == 200
        except:
            return False

    @property
    def api_endpoint(self) -> str:
        """获取 API 端点"""
        return f"{self.base_url}/v1/audio/speech"

    def start(self, wait: bool = True, timeout: int = 30) -> bool:
        """
        启动 Qwen TTS 服务

        Args:
            wait: 是否等待服务启动完成
            timeout: 等待超时时间（秒）

        Returns:
            是否启动成功
        """
        if self.is_running:
            logger.info(f"Qwen TTS 服务已在运行: {self.base_url}")
            return True

        # 确保依赖安装
        self._ensure_dependencies()

        # 设置环境变量
        env = os.environ.copy()
        env["HTTP_PORT"] = str(self.port)
        env["BASE_URL"] = self.BASE_URL

        # 启动服务进程
        try:
            logger.info(f"启动 Qwen TTS 服务...")
            cmd = [sys.executable, "-m", "qwen_tts"]

            self._process = subprocess.Popen(
                cmd,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
            )

            if wait:
                # 等待服务启动
                start_time = time.time()
                while time.time() - start_time < timeout:
                    if self.is_running:
                        logger.info(f"Qwen TTS 服务启动成功: {self.base_url}")
                        return True
                    time.sleep(0.5)
                    # 检查进程是否崩溃
                    if self._process.poll() is not None:
                        stdout, stderr = self._process.communicate()
                        logger.error(f"服务进程退出，stdout: {stdout.decode()}, stderr: {stderr.decode()}")
                        return False

                logger.error(f"服务启动超时 ({timeout}s)")
                return False

            return True

        except Exception as e:
            logger.error(f"启动服务失败: {e}")
            return False

    def stop(self) -> bool:
        """
        停止 Qwen TTS 服务

        Returns:
            是否停止成功
        """
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
                logger.info("Qwen TTS 服务已停止")
                return True
            except subprocess.TimeoutExpired:
                self._process.kill()
                return True
            except Exception as e:
                logger.error(f"停止服务失败: {e}")
                return False
        return True

    def _ensure_dependencies(self) -> None:
        """确保依赖已安装"""
        try:
            import aiohttp
            import aiofiles
            import gradio_client
        except ImportError:
            logger.info("正在安装依赖...")
            # 使用清华镜像加速
            subprocess.run([
                sys.executable, "-m", "pip", "install",
                "aiohttp>=3.9.0", "aiofiles>=25.0.0", "gradio_client>=2.0.0",
                "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"
            ], check=True)

    def fetch_models(self) -> bool:
        """
        获取音色和语言列表

        Returns:
            是否获取成功
        """
        try:
            resp = requests.get(f"{self.base_url}/v1/models", timeout=10)
            resp.raise_for_status()
            data = resp.json()

            self._voices = data.get("voices", {})
            self._languages = data.get("languages", {})

            logger.info(f"获取到 {len(self._voices)} 个音色, {len(self._languages)} 种语言")
            return True

        except Exception as e:
            logger.error(f"获取模型列表失败: {e}")
            return False

    def get_voices(self, force_refresh: bool = False) -> List[VoiceInfo]:
        """
        获取可用音色列表

        Args:
            force_refresh: 是否强制刷新缓存

        Returns:
            音色信息列表
        """
        if force_refresh or not self._voices:
            if not self.fetch_models():
                return []

        return [VoiceInfo.from_api(vid, name) for vid, name in self._voices.items()]

    def get_languages(self, force_refresh: bool = False) -> Dict[str, str]:
        """
        获取可用语言列表

        Args:
            force_refresh: 是否强制刷新缓存

        Returns:
            语言字典 {id: name}
        """
        if force_refresh or not self._languages:
            if not self.fetch_models():
                return {}
        return self._languages.copy()

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: int = 60
    ) -> TTSResult:
        """
        合成语音

        Args:
            text: 要合成的文本
            voice: 音色ID（如不提供使用默认）
            language: 语言ID（如不提供使用自动）
            api_key: API密钥（如服务端配置了 API_KEY）
            timeout: 请求超时时间（秒）

        Returns:
            合成结果
        """
        if not self.is_running:
            return TTSResult(
                success=False,
                error_message="服务未运行，请先调用 start()"
            )

        if not text or not text.strip():
            return TTSResult(
                success=False,
                error_message="文本不能为空"
            )

        # 确保已获取音色列表
        if not self._voices:
            self.fetch_models()

        # 构造请求
        payload = {
            "input": text.strip(),
            "voice": voice or self._get_default_voice(),
            "language": language or "auto"
        }

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            logger.info(f"合成语音: {text[:50]}... | voice={voice} | language={language}")

            resp = requests.post(
                self.api_endpoint,
                json=payload,
                headers=headers,
                timeout=timeout,
                stream=True
            )
            resp.raise_for_status()

            # 读取音频数据
            audio_data = b"".join(resp.iter_content(chunk_size=8192))

            voice_id = resp.headers.get("X-Voice-Id", voice or "default")
            language_id = resp.headers.get("X-Language-Id", language or "auto")
            content_type = resp.headers.get("Content-Type", "audio/wav")

            logger.info(f"合成成功: {len(audio_data)} bytes")

            return TTSResult(
                success=True,
                audio_data=audio_data,
                content_type=content_type,
                voice_id=voice_id,
                language_id=language_id
            )

        except requests.exceptions.RequestException as e:
            logger.error(f"请求失败: {e}")
            return TTSResult(
                success=False,
                error_message=f"请求失败: {str(e)}"
            )
        except Exception as e:
            logger.error(f"合成失败: {e}")
            return TTSResult(
                success=False,
                error_message=f"合成失败: {str(e)}"
            )

    def _get_default_voice(self) -> str:
        """获取默认音色ID"""
        if not self._voices:
            return "vivian"
        # 尝试找到常见的中文音色
        for vid in self._voices.keys():
            if "vivian" in vid.lower() or "十三" in self._voices[vid]:
                return vid
        return list(self._voices.keys())[0]


# ============ Claude Skill 接口 ============

class QwenTTSSkill:
    """
    Claude Skill 接口

    使用方法:
        skill = QwenTTSSkill()
        skill.start_service()
        result = skill.synthesize("你好世界")
        result.save_to_file("output.wav")
    """

    def __init__(self, port: int = 8825, host: str = None, api_key: Optional[str] = None, auto_start: bool = True):
        self.service = QwenTTSService(host=host, port=port)
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
        """启动服务"""
        return self.service.start(wait=wait, timeout=timeout)

    def stop_service(self) -> bool:
        """停止服务"""
        return self.service.stop()

    def ensure_running(self) -> bool:
        """确保服务在运行（自动启动）"""
        if self.service.is_running:
            return True
        if self.auto_start:
            self._auto_started = True
            return self.start_service()
        return False

    def get_voices(self, force_refresh: bool = False) -> Dict[str, str]:
        """获取可用音色字典"""
        if not self.ensure_running():
            return {}
        if force_refresh or not self.service._voices:
            self.service.fetch_models()
        return self.service._voices.copy() if self.service._voices else {}

    def get_languages(self, force_refresh: bool = False) -> Dict[str, str]:
        """获取可用语言字典"""
        if not self.ensure_running():
            return {}
        if force_refresh or not self.service._languages:
            self.service.fetch_models()
        return self.service._languages.copy() if self.service._languages else {}

    def list_voices(self) -> List[Dict[str, str]]:
        """列出可用音色"""
        self.ensure_running()
        voices = self.service.get_voices()
        return [{"id": v.id, "name": v.name} for v in voices]

    def list_languages(self) -> Dict[str, str]:
        """列出可用语言"""
        self.ensure_running()
        return self.service.get_languages()

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        output_path: Optional[str] = None,
        api_key: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        合成语音

        Args:
            text: 要合成的文本
            voice: 音色ID
            language: 语言ID
            output_path: 输出文件路径（可选）
            api_key: API密钥（可选）

        Returns:
            {
                "success": bool,
                "audio_path": str | None,
                "voice_id": str,
                "language_id": str,
                "error": str | None
            }
        """
        self.ensure_running()

        result = self.service.synthesize(text, voice, language, api_key or self.api_key)

        response = {
            "success": result.success,
            "voice_id": result.voice_id,
            "language_id": result.language_id,
            "error": result.error_message,
            "audio_path": None
        }

        if output_path and result.success:
            if result.save_to_file(output_path):
                response["audio_path"] = output_path
        elif result.success:
            # 如果没有指定路径，返回 base64 编码的音频
            response["audio_base64"] = base64.b64encode(result.audio_data).decode()

        return response

    def quick_say(self, text: str, voice: Optional[str] = None, output_path: Optional[str] = None) -> Optional[str]:
        """
        快速语音合成

        Args:
            text: 要合成的文本
            voice: 音色ID（可选）
            output_path: 输出文件路径（可选）

        Returns:
            音频文件路径或 None
        """
        self.ensure_running()
        result = self.service.synthesize(text, voice, "auto", self.api_key)

        if result.success:
            if output_path:
                result.save_to_file(output_path)
                return output_path
            # 保存到临时文件
            import tempfile
            temp_path = tempfile.mktemp(suffix=".wav")
            result.save_to_file(temp_path)
            return temp_path
        return None

    def get_api_info(self) -> Dict[str, Any]:
        """获取 API 信息"""
        return {
            "endpoint": self.service.api_endpoint,
            "running": self.service.is_running,
            "base_url": self.service.base_url,
            "documentation": "https://github.com/aahl/qwen-tts2api"
        }

    def __enter__(self):
        """上下文管理器入口"""
        self.ensure_running()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        if self._auto_started:
            self.stop_service()
        return False


# ============ 便捷函数（顶层 API） ============

_service_instance: Optional[QwenTTSService] = None

def get_service(port: int = 8825) -> QwenTTSService:
    """获取或创建服务实例"""
    global _service_instance
    if _service_instance is None or _service_instance.port != port:
        _service_instance = QwenTTSService(port=port)
    return _service_instance

def ensure_service(port: int = 8825) -> bool:
    """确保服务运行"""
    service = get_service(port)
    if not service.is_running:
        return service.start()
    return True

def skill_start(port: int = 8825, auto_start: bool = True) -> QwenTTSSkill:
    """
    启动并返回一个 skill 实例

    Args:
        port: 服务端口
        auto_start: 是否自动启动服务

    Returns:
        QwenTTSSkill 实例
    """
    skill = QwenTTSSkill(port=port, auto_start=auto_start)
    if auto_start:
        skill.start_service()
    return skill

def skill_say(text: str, voice: Optional[str] = None, port: int = 8825, output_path: Optional[str] = None) -> Optional[str]:
    """
    快速语音合成 - 一句话 TTS

    Args:
        text: 要合成的文本
        voice: 音色ID（可选）
        port: 服务端口
        output_path: 输出文件路径（可选）

    Returns:
        音频文件路径或 None
    """
    with QwenTTSSkill(port=port, auto_start=True) as skill:
        return skill.quick_say(text, voice, output_path)

def skill_voices(port: int = 8825) -> List[Dict[str, str]]:
    """
    获取可用音色列表

    Args:
        port: 服务端口

    Returns:
        音色列表
    """
    with QwenTTSSkill(port=port, auto_start=True) as skill:
        return skill.list_voices()

def skill_languages(port: int = 8825) -> Dict[str, str]:
    """
    获取可用语言列表

    Args:
        port: 服务端口

    Returns:
        语言字典
    """
    with QwenTTSSkill(port=port, auto_start=True) as skill:
        return skill.list_languages()

def tts(
    text: str,
    voice: Optional[str] = None,
    language: Optional[str] = None,
    output_path: Optional[str] = None,
    port: int = 8825
) -> str:
    """
    简单的 TTS 接口

    自动启动服务，合成语音，保存到文件

    Args:
        text: 要合成的文本
        voice: 音色ID
        language: 语言ID
        output_path: 输出路径（默认为 output.wav）
        port: 服务端口号

    Returns:
        输出文件路径或错误信息
    """
    service = get_service(port)

    with QwenTTSSkill(port=port) as skill:
        result = skill.synthesize(text, voice, language, output_path)

        if result["success"]:
            return result.get("audio_path") or "合成成功"
        else:
            return f"失败: {result['error']}"


# 向后兼容别名
QwenTTS = QwenTTSSkill


# ============ CLI 接口 ============

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Qwen TTS Skill")
    parser.add_argument("--start", action="store_true", help="启动服务")
    parser.add_argument("--stop", action="store_true", help="停止服务")
    parser.add_argument("--say", type=str, help="合成语音文本")
    parser.add_argument("--voice", type=str, help="音色ID")
    parser.add_argument("--language", type=str, help="语言ID")
    parser.add_argument("--list-voices", action="store_true", help="列出可用音色")
    parser.add_argument("--list-languages", action="store_true", help="列出可用语言")
    parser.add_argument("--output", type=str, help="输出文件路径")
    parser.add_argument("--port", type=int, default=8825, help="服务端口")

    args = parser.parse_args()

    skill = QwenTTSSkill(port=args.port)

    if args.start:
        success = skill.start_service()
        print(f"服务 {'启动成功' if success else '启动失败'}")

    elif args.stop:
        success = skill.stop_service()
        print(f"服务 {'已停止' if success else '未运行'}")

    elif args.say:
        result = skill.quick_say(args.say, args.voice, args.output)
        if result:
            print(f"音频已保存到: {result}")
        else:
            print("合成失败")

    elif args.list_voices:
        voices = skill.list_voices()
        print("可用音色:")
        for v in voices:
            print(f"  - {v['id']}: {v['name']}")

    elif args.list_languages:
        languages = skill.list_languages()
        print("可用语言:")
        for lid, lname in languages.items():
            print(f"  - {lid}: {lname}")

    else:
        parser.print_help()
