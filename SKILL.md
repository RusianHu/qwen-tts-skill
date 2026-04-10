---
name: qwen-tts
description: >
  将文本合成为语音（TTS）。当用户要求语音合成、朗读文本、生成音频文件、text-to-speech、tts、语音合成、
  将文字转为语音、读一段文字给我听、生成 wav/mp3 音频时触发此技能。支持中文/英文多语言自动检测，
  可选音色，输出 OpenAI 兼容格式的音频。即使用户没有明确提到 "tts" 或 "语音合成"，
  只要用户要求"读出来"、"生成音频"、"播放这段文字"，就应该使用此技能。
---

## 使用方法

当需要语音合成时，按以下步骤操作：

### 1. 快速合成（一句话调用）

```python
from qwen_tts_skill import skill_say
audio_path = skill_say("你好，世界！")
```

这是最简单的方式——自动启动服务、合成语音、返回音频文件路径。适用于大多数场景。

### 2. 完整调用（需要指定音色/语言/输出路径）

```python
from qwen_tts_skill import QwenTTSSkill

with QwenTTSSkill() as skill:
    result = skill.synthesize(
        text="你好，这是 Qwen TTS！",
        voice="vivian",        # 可选，默认自动选择
        language="zh",         # 可选，默认 auto 自动检测
        output_path="output.wav"  # 可选，不提供则返回 base64
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
```

## 参数说明

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `text` | str | 是 | - | 要合成的文本内容 |
| `voice` | str | 否 | 自动选择第一个可用音色（通常为 vivian） | 音色 ID，通过 `skill_voices()` 获取 |
| `language` | str | 否 | `"auto"` | 语言 ID（`zh`=中文, `en`=英文, `auto`=自动检测） |
| `output_path` | str | 否 | 临时 `.wav` 文件 | 输出音频的保存路径 |
| `port` | int | 否 | `8825` | 服务端口，通常不需要修改 |

## 重要注意事项

- **首次使用会自动安装依赖**（aiohttp, aiofiles, gradio_client），可能需要几秒钟
- **服务是自动管理的**：`skill_say` 和 `QwenTTSSkill` 的上下文管理器模式会自动启动/停止服务，不需要手动管理
- **长文本建议分段**：如果文本非常长（超过几千字），建议分段合成，避免超时
- **输出格式**：默认为 WAV 格式，如需其他格式（MP3 等）需要在合成后自行转换
- **环境变量**：可通过 `BASE_URL` 环境变量修改上游 TTS 服务地址，通过 `HTTP_PORT` 修改端口
- **失败处理**：如果 `result["success"]` 为 `false`，检查 `result["error"]` 字段获取错误信息

## 常见触发场景示例

- "帮我读一下这段文字：..."
- "生成一段语音说..."
- "把这句话转成音频"
- "用中文朗读以下内容"
- "text to speech for ..."
- "tts: ..."
- "我想听这段文字被念出来"
- "生成一个 wav 文件"
