# Qwen TTS Skill

面向 AI Agent / 自动化工具的 **自包含 Claude Skill**，通过 qwen-tts 服务将文本转换为语音。

本项目基于远端 Qwen TTS Gradio 服务，提供：

- 文本转语音能力
- 音色 / 语言枚举查询
- 可选的 OpenAI 兼容 REST API
- 可嵌入 Python 流程的 skill 级调用方式

## 安装方式

### 1. 推荐：让 Agent 安装整个 skill 仓库

直接告诉你的 **claude code 、 codex 、龙虾**  ：

```text
帮我安装这个 skill：https://github.com/RusianHu/qwen-tts-skill
```

安装后，Agent 应能在该 skill 目录内看到 [`SKILL.md`](SKILL.md) 与 [`scripts/`](scripts) 等文件。

### 2. 手动安装依赖（仅当环境缺少依赖时）

在 skill 根目录执行：

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

> 注意：本项目在运行时**不会自动执行** `pip install`。如果缺少依赖，会提示你手动安装 [`requirements.txt`](requirements.txt) 中的内容。

## 快速开始

下文中的 `<SKILL_DIR>` 指本 skill 的**安装目录绝对路径**。脚本自包含，
可跨目录用绝对路径调用，**无需 `cd`、无需 pip 安装**。
写成相对路径（`scripts/qwen_tts_skill.py`）仅在 skill 根目录下成立。

### 1. 直接合成一段语音（首选）

```bash
python <SKILL_DIR>/scripts/qwen_tts_skill.py --say "你好，世界！" --output output.wav
```

指定音色与语言：

```bash
python <SKILL_DIR>/scripts/qwen_tts_skill.py --say "你好，这是 Qwen TTS！" --voice vivian --language zh --output output.wav
```

### 2. 查询可用音色（共 49 个）

```bash
python <SKILL_DIR>/scripts/qwen_tts_skill.py --list-voices
```

### 3. 查询可用语言（共 11 种）

```bash
python <SKILL_DIR>/scripts/qwen_tts_skill.py --list-languages
```

### 4. 作为独立 REST 服务运行（可选）

```bash
python <SKILL_DIR>/scripts/server.py
```

或：

```bash
python <SKILL_DIR>/scripts/qwen_tts_skill.py --serve --host 0.0.0.0 --port 8825
```

> 首次在全新环境使用时若缺少依赖，脚本会直接给出安装提示，不会抛出裸 traceback。

## Python 中如何集成

`scripts/` 不是常规包（没有 `__init__.py`），**必须先把 `<SKILL_DIR>/scripts` 加入 `sys.path`**，
再导入 [`qwen_tts_skill`](scripts/qwen_tts_skill.py)，否则会 `ImportError`。

```python
from pathlib import Path
import sys

SKILL_DIR = r"<SKILL_DIR>"          # ← skill 安装目录的绝对路径
scripts_dir = Path(SKILL_DIR) / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from qwen_tts_skill import QwenTTSSkill

with QwenTTSSkill() as skill:
    result = skill.synthesize(
        text="你好，这是 Qwen TTS！",
        voice="vivian",
        language="zh",
        output_path="output.wav",
    )
    print(result)
```

快速函数：

```python
from pathlib import Path
import sys

SKILL_DIR = r"<SKILL_DIR>"
scripts_dir = Path(SKILL_DIR) / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from qwen_tts_skill import skill_say, skill_voices, skill_languages

output = skill_say("你好，世界！", voice="vivian", output_path="output.wav")
print(output)
print(skill_voices())
print(skill_languages())
```

> 重点：不要把"skill 文件已下载到本地"和"Python 包已被安装到环境"当成同一件事。  
> skill 分发后，最稳妥的调用方式仍然是直接执行 [`scripts/qwen_tts_skill.py`](scripts/qwen_tts_skill.py) 的绝对路径。

## 验证方式

### 1. 自包含验证

在 skill 根目录执行：

```bash
python verify.py
```

这个脚本会检查：

- skill 关键文件是否齐全
- [`scripts/qwen_tts_skill.py`](scripts/qwen_tts_skill.py) 能否在当前目录模型下导入
- [`scripts/server.py`](scripts/server.py) 能否在未 `pip install -e .` 的前提下工作
- 依赖状态与模式元数据是否正确

### 2. 测试

```bash
pytest tests/test_skill.py -q
```

默认跳过需要真实上游的用例。要连同真实上游一起验证：

```bash
QWEN_TTS_NETWORK_TESTS=1 pytest tests/test_skill.py -q
```

## API 端点

仅在你显式启动 REST 服务后，可使用以下端点：

| 端点 | 方法 | 描述 |
|------|------|------|
| `GET /` | GET | 服务信息 |
| `GET /health` | GET | 健康检查 |
| `GET /v1/models` | GET | 获取模型、音色、语言列表 |
| `GET /v1/voices` | GET | 获取音色列表 |
| `POST /v1/audio/speech` | POST | 文本转语音 |

### cURL 示例

```bash
curl -X POST http://localhost:8825/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{
    "input": "你好，这是测试",
    "voice": "vivian",
    "language": "zh"
  }' \
  --output test.wav
```

## 配置项

环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HTTP_HOST` | `0.0.0.0` | REST 服务监听地址 |
| `HTTP_PORT` | `8825` | REST 服务端口 |
| `BASE_URL` | `https://qwen-qwen3-tts-demo.hf.space` | 远端 Qwen TTS Gradio 服务地址 |
| `API_KEY` | - | REST API 鉴权密钥（可选）；同时会作为 `Authorization: Bearer` 透传给上游 |
| `QWEN_TTS_MAX_ATTEMPTS` | `3` | 单次合成最大尝试次数（上游偶发失败时自动重试） |
| `QWEN_TTS_RETRY_DELAY` | `2` | 重试基础间隔秒数，按尝试次数递增 |

> **上游变更说明（2026-09）**
> 原默认上游 `https://qwen-qwen3-tts-demo.ms.show` 已停止服务（HTTP 403，官方提示改走
> 需要 ModelScope token 的 `api-inference` 地址）。现默认上游切换为
> `https://qwen-qwen3-tts-demo.hf.space`，其 `/tts_interface` 参数签名
> （`text` / `voice_display` / `language_display`）与原上游一致，免鉴权，
> 输出同样为 24kHz / 单声道 / 16bit WAV。
> 若你有 ModelScope token，可通过 `BASE_URL` 指回官方 API 地址并配置 `API_KEY`。

## 依赖分层

`requirements.txt` 会一次装齐，但两种依赖的职责是分开的：

| 层级 | 依赖 | 用于 |
|------|------|------|
| 核心（必需） | `requests`、`gradio_client` | `--say`、`--list-voices`、`--list-languages`、Python API |
| REST（可选） | `fastapi`、`uvicorn`、`pydantic` | 仅启动 REST 服务时需要 |

核心调用链不导入 Web 框架栈，因此只装核心依赖也能正常合成语音。
缺少任一依赖时脚本会给出明确的安装提示，不会抛出裸 traceback。

## 兼容性说明

- 本项目仍然依赖**远端** Qwen TTS Gradio 服务进行最终音频生成
- 但已经不再依赖**本地** `qwen-tts2api` 仓库、包安装或其进程启动
- 当前推荐路径是 **skill 自包含目录 + 绝对路径直接脚本调用**
- Python 导入模式需要显式把 [`scripts/`](scripts) 加入 `sys.path`
- OpenAI 风格 REST 能力作为**可选暴露层**保留
- 当前实现**不会在运行时自动安装依赖**；缺少依赖时会直接给出明确提示
- 上游为免费 HuggingFace Space：短文本约 10-15s，1000 字约 6 分钟，且可能休眠冷启动

## 开发说明

[`pyproject.toml`](pyproject.toml) 仍然保留，用于：

- 本地开发
- 运行测试
- 可选地以 Python 包形式调试

但对 **skill 最终使用者 / Agent 安装场景** 来说，**不应把它当作默认前提**。

## 更新日志

版本历史与破坏性变更见 [CHANGELOG.md](CHANGELOG.md)。
当前版本 **0.3.0**（2026-09-09，默认上游已更换，详见变更日志）。

## 许可证

[MIT](LICENSE)
