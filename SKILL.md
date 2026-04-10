---
name: qwen-tts
description: >
  将文本合成为语音（TTS）。当用户要求语音合成、朗读文本、生成音频文件、text-to-speech、tts、语音合成、
  将文字转为语音、读一段文字给我听、生成 wav/mp3 音频时触发此技能。支持中文/英文多语言自动检测，
  可选音色，输出 OpenAI 兼容格式的音频。即使用户没有明确提到 "tts" 或 "语音合成"，
  只要用户要求"读出来"、"生成音频"、"播放这段文字"，就应该使用此技能。
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

## 推荐调用方式（推荐使用实际部署后的绝对路径）

### 1. 快速合成单段文本（首选）

优先直接执行 [`scripts/qwen_tts_skill.py`](scripts/qwen_tts_skill.py)：

```bash
python scripts/qwen_tts_skill.py --say "你好，世界！" --output output.wav
```

如需指定音色或语言：

```bash
python scripts/qwen_tts_skill.py --say "你好，这是 Qwen TTS！" --voice vivian --language zh --output output.wav
```

适用场景：
- 用户只想把一段文本转成音频
- 需要得到本地 `.wav` 文件
- 不需要额外启动 REST 服务

### 2. 获取可用音色列表

```bash
python scripts/qwen_tts_skill.py --list-voices
```

### 3. 获取可用语言列表

```bash
python scripts/qwen_tts_skill.py --list-languages
```

### 4. 以 REST 服务方式运行（可选）

如果调用方必须使用 HTTP / OpenAI 风格接口，再启动可选 REST 服务：

```bash
python scripts/server.py
```

或：

```bash
python scripts/qwen_tts_skill.py --serve --host 0.0.0.0 --port 8825
```

## Python 集成方式

只有在你**明确知道当前 skill 根目录路径**时，才建议在 Python 中导入。

关键原则：先把 [`scripts/`](scripts) 加入 `sys.path`，再导入 [`qwen_tts_skill`](scripts/qwen_tts_skill.py)。

### 1. 完整调用（推荐模板）

```python
from pathlib import Path
import sys

skill_root = Path(".").resolve()
scripts_dir = skill_root / "scripts"
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

scripts_dir = (Path(".").resolve() / "scripts")
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

scripts_dir = (Path(".").resolve() / "scripts")
if str(scripts_dir) not in sys.path:
    sys.path.insert(0, str(scripts_dir))

from qwen_tts_skill import skill_voices, skill_languages

print(skill_voices())
print(skill_languages())
```

如果当前 Python 进程**不在 skill 根目录下**运行，请先把 `skill_root` 改成当前已安装 skill 的绝对路径，再拼出 [`scripts/`](scripts) 路径。

## 参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `text` | str | 是 | - | 要合成的文本内容 |
| `voice` | str | 否 | 自动选择默认音色（通常为 `vivian`） | 音色 ID，可通过 [`--list-voices`](scripts/qwen_tts_skill.py) 或 [`skill_voices()`](scripts/qwen_tts_skill.py:786) 获取 |
| `language` | str | 否 | `"auto"` | 语言 ID，如 `zh`、`en`、`auto` |
| `output_path` | str | 否 | 临时 `.wav` 文件 | 输出音频保存路径 |
| `port` | int | 否 | `8825` | 仅在启用本地 REST 服务时使用 |

## 验证方式

在当前 skill 根目录执行：

```bash
python verify.py
```

如需运行测试：

```bash
pytest tests/test_skill.py -q
```

## 重要注意事项

- **当前实现是 skill 自包含的**：核心逻辑位于 [`scripts/qwen_tts_skill.py`](scripts/qwen_tts_skill.py)
- **不要把 skill 分发与 pip 包安装混为一谈**：脚本文件会随 skill 下发，但不会因此自动变成全局可导入包
- **默认优先走脚本路径调用**：最稳妥的方式是直接执行 [`python scripts/qwen_tts_skill.py --say ...`](scripts/qwen_tts_skill.py)
- **Python 导入需要显式处理路径**：如需导入，请先把 [`scripts/`](scripts) 加入 `sys.path`
- **REST 是可选暴露层**：只有在你显式启动服务时，才会监听本地端口并提供 OpenAI 风格接口
- **仍然依赖远端上游服务**：实际音频生成由 `BASE_URL` 指向的远端 Qwen TTS Gradio 服务完成
- **首次调用可能稍慢**：需要探测远端音色/语言列表
- **长文本建议分段**：非常长的文本建议拆分后分段合成，避免超时
- **输出格式默认是 WAV**：如需 MP3 等其他格式，可在生成后自行转换
- **环境变量可配置**：
  - `BASE_URL`：远端 Qwen TTS 服务地址
  - `HTTP_HOST`：本地 REST 服务监听地址
  - `HTTP_PORT`：本地 REST 服务监听端口
  - `API_KEY`：本地 REST API 鉴权密钥
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
