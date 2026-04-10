"""Qwen TTS FastAPI server entrypoint.

当前文件仅作为独立服务启动入口，
实际 REST API 实现在 [`create_app()`](scripts/qwen_tts_skill.py:676)
与 [`start_server()`](scripts/qwen_tts_skill.py:773) 中统一维护。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from qwen_tts_skill import create_app, start_server


BASE_URL = os.getenv("BASE_URL")
API_KEY = os.getenv("API_KEY")
HTTP_HOST = os.getenv("HTTP_HOST", "0.0.0.0")
HTTP_PORT = int(os.getenv("HTTP_PORT", "8825"))

app = create_app(upstream_url=BASE_URL, api_key=API_KEY)


def main() -> None:
    start_server(
        host=HTTP_HOST,
        port=HTTP_PORT,
        upstream_url=BASE_URL,
        api_key=API_KEY,
    )


if __name__ == "__main__":
    main()
