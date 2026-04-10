---
name: qwen-tts
description: >
  将文本合成为语音（TTS）。当用户要求语音合成、朗读文本、生成音频文件、text-to-speech、tts、语音合成、
  将文字转为语音、读一段文字给我听、生成 wav/mp3 音频时触发此技能。支持中文/英文多语言自动检测，
  可选音色，输出 OpenAI 兼容格式的音频。即使用户没有明确提到 "tts" 或 "语音合成"，
  只要用户要求"读出来"、"生成音频"、"播放这段文字"，就应该使用此技能。
---

## 使用方法

当需要语音合成时，优先使用当前仓库内置的独立实现。
所需的 Python 适配逻辑已内置在当前项目中。

### 1. 快速合成（一句话调用）

```python
from qwen_tts_skill import skill_say

audio_path = skill_say("你好，世界！")
```

这是最简单的方式：直接调用当前项目内置后端完成合成并返回音频文件路径。
适用于大多数场景。

### 2. 完整调用（需要指定音色/语言/输出路径）

```python
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

### 3. 获取可用音色列表

```python
from qwen_tts_skill import skill_voices

voices = skill_voices()
for v in voices:
    print(f"{v['id']}: {v['name']}")
```

### 4. 获取可用语言列表

```python
from qwen_tts_skill import skill_languages

languages = skill_languages()
print(languages)
```

### 5. 以 REST 服务方式运行（可选）

```bash
python scripts/server.py
```

或：

```bash
python scripts/qwen_tts_skill.py --serve --host 0.0.0.0 --port 8825
```

## 参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `text` | str | 是 | - | 要合成的文本内容 |
| `voice` | str | 否 | 自动选择默认音色（通常为 `vivian`） | 音色 ID，通过 `skill_voices()` 获取 |
| `language` | str | 否 | `"auto"` | 语言 ID，如 `zh`、`en`、`auto` |
| `output_path` | str | 否 | 临时 `.wav` 文件 | 输出音频保存路径 |
| `port` | int | 否 | `8825` | 仅在启用本地 REST 服务时使用 |

## 重要注意事项

- **当前实现是独立的**：不再依赖本地 `qwen-tts2api` 仓库、包安装或其服务进程
- **Python 默认直连后端**：`skill_say` 和 `QwenTTSSkill` 默认不会绕本地 REST 中间层
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
