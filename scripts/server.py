"""Qwen TTS FastAPI server entrypoint.

当前文件仅作为独立服务启动入口，
实际 REST API 实现在 [`create_app()`](scripts/qwen_tts_skill.py)
与 [`start_server()`](scripts/qwen_tts_skill.py) 中统一维护。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from qwen_tts_skill import (
    create_app,
    parse_env_int,
    resolve_rest_api_key,
    resolve_upstream_api_key,
    start_server,
)


BASE_URL = os.getenv("BASE_URL")
# 默认只监听本机回环地址：这是被 Agent 自动拉起的本地服务，
# 不应默认暴露到局域网。需要外部访问时显式设置 HTTP_HOST=0.0.0.0。
HTTP_HOST = os.getenv("HTTP_HOST", "127.0.0.1")
HTTP_PORT = parse_env_int("HTTP_PORT", 8825, minimum=1, maximum=65535)

app = create_app(
    upstream_url=BASE_URL,
    api_key=resolve_rest_api_key(),
    upstream_api_key=resolve_upstream_api_key(),
)


def main() -> None:
    start_server(
        host=HTTP_HOST,
        port=HTTP_PORT,
        upstream_url=BASE_URL,
        api_key=resolve_rest_api_key(),
        upstream_api_key=resolve_upstream_api_key(),
    )


if __name__ == "__main__":
    main()
