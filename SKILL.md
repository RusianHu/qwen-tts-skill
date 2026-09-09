---
name: qwen-tts-skill
license: MIT
description: >
  将文本合成为语音（TTS）。当用户要求语音合成、朗读文本、生成音频文件、text-to-speech、tts、语音合成、
  将文字转为语音、读一段文字给我听、生成 wav 音频时触发此技能。内置 49 个音色（含粤语、四川话等方言），
  支持中文、英文、日语、韩语、德语、法语、俄语、葡语、西语、意语共 10 种语言及自动检测，
  输出 24kHz 单声道 16bit WAV 文件；也可按需启动 OpenAI 兼容的本地 REST 服务。
  即使用户没有明确提到 "tts" 或 "语音合成"，只要用户要求"读出来"、"生成音频"、
  "播放这段文字"，就应该使用此技能。注意：合成依赖远端服务，需要联网；
  首次使用需按 SKILL.md 安装 requirements.txt 依赖。
---

## 使用原则

此 skill 采用**自包含分发**模型：

- [`SKILL.md`](SKILL.md) 与 [`scripts/qwen_tts_skill.py`](scripts/qwen_tts_skill.py)、[`scripts/server.py`](scripts/server.py) 一起随 skill 分发
- **不要默认假设**当前环境已经执行过 `pip install -e .`
- 优先直接使用当前 skill 目录中的脚本文件路径
- 仅当依赖缺失时，再在当前 skill 目录安装 [`requirements.txt`](requirements.txt) 中的依赖

如果当前环境缺少依赖，先在 **当前 skill 根目录** 执行：

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

## 推荐调用方式

下面的 `<SKILL_DIR>` 一律替换为**本 skill 的实际安装目录（绝对路径）**。
脚本是自包含的，可以跨目录用绝对路径直接调用，**不需要先 `cd` 到 skill 目录，也不需要 pip 安装**。

> 注意：
> - 写成相对路径（`scripts/qwen_tts_skill.py`）只有当你已在 skill 根目录下才成立，
>   在其他工作目录会报 `can't open file`。**默认请使用绝对路径。**
> - 安装路径含空格时，shell 里必须给路径加引号：
>   `python "$SKILL_DIR/scripts/qwen_tts_skill.py" ...`（POSIX）
>   或 `python "$env:SKILL_DIR\scripts\qwen_tts_skill.py" ...`（PowerShell）。

### 1. 快速合成单段文本（首选）

```bash
python <SKILL_DIR>/scripts/qwen_tts_skill.py --say "你好，世界！" --output output.wav
```

如需指定音色或语言：

```bash
python <SKILL_DIR>/scripts/qwen_tts_skill.py --say "你好，这是 Qwen TTS！" --voice vivian --language zh --output output.wav
```

适用场景：
- 用户只想把一段文本转成音频
- 需要得到本地 `.wav` 文件
- 不需要额外启动 REST 服务

### 2. 获取可用音色列表（49 个）

```bash
python <SKILL_DIR>/scripts/qwen_tts_skill.py --list-voices
```

输出形如 `vivian: Vivian / 十三`。冒号左侧即 `--voice` 要传的 ID。
含普通话、英语及粤语 / 四川 / 北京 / 上海 / 闽南 / 天津 / 陕西 / 南京等方言音色。

### 3. 获取可用语言列表（11 种）

```bash
python <SKILL_DIR>/scripts/qwen_tts_skill.py --list-languages
```

### 4. 以 REST 服务方式运行（可选）

如果调用方必须使用 HTTP / OpenAI 风格接口，再启动可选 REST 服务：

```bash
python <SKILL_DIR>/scripts/server.py
```

或：

```bash
python <SKILL_DIR>/scripts/qwen_tts_skill.py --serve --host 0.0.0.0 --port 8825
```

## Python 集成方式

只有在你**明确知道 skill 安装目录的绝对路径**时，才建议在 Python 中导入。

关键原则：先把 `<SKILL_DIR>/scripts` 加入 `sys.path`，再导入 [`qwen_tts_skill`](scripts/qwen_tts_skill.py)。
`scripts/` 不是常规包（没有 `__init__.py`），**不做这一步会 ImportError**。

### 1. 完整调用（推荐模板）

```python
from pathlib import Path
import sys

SKILL_DIR = r"<SKILL_DIR>"          # ← 替换为 skill 安装目录的绝对路径
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
    if result["success"]:
        print(f"音频路径: {result['audio_path']}")
    else:
        print(f"失败: {result['error']}")
```

### 2. 快速语音合成

```python
from pathlib import Path
import sys

SKILL_DIR = r"<SKILL_DIR>"
scripts_dir = Path(SKILL_DIR) / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from qwen_tts_skill import skill_say

audio_path = skill_say("你好，世界！", voice="vivian", output_path="output.wav")
print(audio_path)
```

### 3. 获取音色 / 语言

```python
from pathlib import Path
import sys

SKILL_DIR = r"<SKILL_DIR>"
scripts_dir = Path(SKILL_DIR) / "scripts"
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from qwen_tts_skill import skill_voices, skill_languages

print(skill_voices())     # [{"id": "vivian", "name": "Vivian / 十三"}, ...]
print(skill_languages())  # {"auto": "Auto / 自动", "chinese": "Chinese / 中文", ...}
```

## 参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `text` | str | 是 | - | 要合成的文本内容 |
| `voice` | str | 否 | 自动选择默认音色 `vivian` | 音色 ID（共 49 个），通过 [`--list-voices`](scripts/qwen_tts_skill.py) 获取。匹配忽略大小写与分隔符，`ono-anna` / `onoanna` 均可命中 `ono anna`；传入无效值会回退默认音色而非报错 |
| `language` | str | 否 | `"auto"` | 语言 ID。推荐 `zh`、`en`、`ja`、`ko`、`de`、`fr`、`ru`、`pt`、`es`、`it`、`auto`；也接受上游全拼 `chinese`、`english` 等 |
| `output_path` | str | 否 | 临时 `.wav` 文件 | 输出音频保存路径 |
| `port` | int | 否 | `8825` | 仅在启用本地 REST 服务时使用 |

## 验证方式

自检（建议在 skill 根目录执行）：

```bash
cd <SKILL_DIR> && python verify.py
```

运行测试：

```bash
cd <SKILL_DIR> && pytest tests/test_skill.py -q
```

默认会跳过需要真实上游的用例；要连真实验证则：

```bash
cd <SKILL_DIR> && QWEN_TTS_NETWORK_TESTS=1 pytest tests/test_skill.py -q
```

## 重要注意事项

- **当前实现是 skill 自包含的**：核心逻辑位于 [`scripts/qwen_tts_skill.py`](scripts/qwen_tts_skill.py)
- **不要把 skill 分发与 pip 包安装混为一谈**：脚本文件会随 skill 下发，但不会因此自动变成全局可导入包
- **默认优先走脚本路径调用**：最稳妥的方式是用绝对路径直接执行
  `python <SKILL_DIR>/scripts/qwen_tts_skill.py --say ...`
- **Python 导入需要显式处理路径**：如需导入，请先把 `<SKILL_DIR>/scripts` 加入 `sys.path`
- **REST 是可选暴露层**：只有在你显式启动服务时，才会监听本地端口并提供 OpenAI 风格接口
- **仍然依赖远端上游服务**：实际音频生成由 `BASE_URL` 指向的远端 Qwen TTS Gradio 服务完成
- **默认上游为 `https://qwen-qwen3-tts-demo.hf.space`**：共 49 个音色、11 种语言；原 `qwen-qwen3-tts-demo.ms.show` 已废弃（403）
- **仅支持 Gradio-compatible 上游**：`BASE_URL` 可换成任何暴露 `/tts_interface`（`text` / `voice_display` / `language_display`）签名的 Gradio 服务；需要鉴权的上游请设置 `QWEN_TTS_UPSTREAM_API_KEY`。**不能**直接指向 ModelScope / DashScope 的 REST 推理 API（协议不同）
- **本地 REST 密钥与上游凭据分离**：`QWEN_TTS_REST_API_KEY`（或旧变量 `API_KEY`，已废弃）只保护本地服务，**绝不会**发给远端；上游凭据用 `QWEN_TTS_UPSTREAM_API_KEY`
- **首次调用可能稍慢**：需要探测远端音色/语言列表；HuggingFace Space 冷启动可能额外等待数十秒
- **输出格式为 24kHz / 单声道 / 16bit WAV**：如需 MP3 等其他格式，可在生成后自行转换
- **长文本量级参考**：实测单段 1000 字可合成约 4.4 分钟音频（耗时约 6 分钟）；
  更长的文本建议拆分分段合成，避免单次等待过久
- **音色 ID 容错**：匹配时忽略大小写与分隔符，`ono-anna` / `onoanna` 均可命中 `ono anna`；
  传入不存在的音色会回退到默认音色 `vivian`，不会报错
- **环境变量可配置**：
  - `BASE_URL`：远端 Qwen TTS 服务地址（Gradio-compatible）
  - `QWEN_TTS_UPSTREAM_API_KEY`：上游凭据（默认上游免鉴权，无需配置）
  - `QWEN_TTS_REST_API_KEY`：本地 REST 鉴权密钥（绝不发送给远端）
  - `API_KEY`：⚠️ 已废弃，等价于 `QWEN_TTS_REST_API_KEY`；不会发给上游
  - `HTTP_HOST`：本地 REST 服务监听地址（默认 `127.0.0.1`，暴露外网需显式设置）
  - `HTTP_PORT`：本地 REST 服务监听端口
  - `QWEN_TTS_CORS_ORIGINS`：允许的跨域来源（默认关闭 CORS）
  - `QWEN_TTS_MAX_ATTEMPTS`：单次合成最大尝试次数（默认 `3`）
  - `QWEN_TTS_RETRY_DELAY`：重试基础间隔秒数（默认 `2`，按次数递增）
- **CLI 退出码**：`0` 成功；`1` 合成/上游失败；`2` 参数错误；`3` 配置/依赖错误。
  配合 `--json` 可让 Agent 稳定解析结果
- **上游抖动会自动重试**：托管型 Space 偶发失败（实测约 2% 概率），默认重试 3 次即可兜住，无需调用方处理
- **失败处理**：如果 `result["success"]` 为 `false`，请检查 `result["error"]`

## 常见触发场景示例

- "帮我读一下这段文字：..."
- "生成一段语音说..."
- "把这句话转成音频"
- "用中文朗读以下内容"
- "text to speech for ..."
- "tts: ..."
- "我想听这段文字被念出来"
- "生成一个 wav 文件"
