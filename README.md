# Qwen TTS Skill

 Python REST Skill for Qwen TTS。

本项目基于 `qwen-tts-api` ，提供给你的 AI AGENT /自动化工具 语音生成服务，能力基于：

- 将官方 Qwen TTS Gradio 接口适配为 Python 可直接调用的后端
- 可选暴露为 OpenAI 兼容的 REST API
- 提供便捷的 Python Skill API
- 可单独启动 FastAPI 服务运行

## 安装

一句话搞定，直接和你的 **claude code 、codex 、龙虾** 说（推荐）

```text
帮我安装这个skill （https://github.com/RusianHu/qwen-tts-skill）
```

手动安装项目依赖：

```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e .
```

> 注意：项目不会在运行时自动执行 `pip install`。如果要使用可选 REST 服务，请先完成依赖安装。

安装后将获得命令行入口：

```bash
qwen-tts-skill --help
```

## 架构说明

当前项目的独立实现由两层组成：

1. **内置 Python 适配后端**  
   在 [`scripts/qwen_tts_skill.py`](scripts/qwen_tts_skill.py) 中实现：
   - 发现远端 Gradio 的音色/语言枚举
   - 调用 `/tts_interface` 完成合成
   - 将结果转成统一的 [`TTSResult`](scripts/qwen_tts_skill.py:51)
   - 这是 Python API 的默认调用路径

2. **可选本地 OpenAI 风格 REST 服务**  
   通过 [`create_app()`](scripts/qwen_tts_skill.py:703) 与 [`start_server()`](scripts/qwen_tts_skill.py:790) 暴露：
   - `GET /v1/models`
   - `GET /v1/voices`
   - `POST /v1/audio/speech`
   - `GET /health`

## 快速开始

### 1. 作为 Python 模块使用（默认直连后端）

```python
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

这里的 Python 调用**默认不会启动本地 REST 服务**，而是直接调用内置后端。

### 2. 快速语音合成

```python
from qwen_tts_skill import skill_say, skill_voices, skill_languages

output = skill_say("你好，世界！", voice="vivian")
print(output)

voices = skill_voices()
print(voices)

languages = skill_languages()
print(languages)
```

### 3. 作为独立 REST 服务运行（可选）

在启动前，请确认已经执行过 [`pip install -e .`](README.md:26) 安装完整依赖；当前实现若检测到缺少 REST 依赖，会直接报错提示，而不会在运行时自动联网安装。

#### 方式 A：直接运行 FastAPI 服务入口

```bash
python scripts/server.py
```

#### 方式 B：使用模块 CLI 以前台方式启动

```bash
python scripts/qwen_tts_skill.py --serve --host 0.0.0.0 --port 8825
```

#### 方式 C：使用安装后的命令行入口

```bash
qwen-tts-skill --serve --host 0.0.0.0 --port 8825
```

### 4. 可选 REST 服务管理

```python
from qwen_tts_skill import QwenTTSSkill

skill = QwenTTSSkill(port=8825)
skill.start_service()
print(skill.get_api_info())
skill.stop_service()
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

## 配置选项

环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HTTP_HOST` | `0.0.0.0` | REST 服务监听地址 |
| `HTTP_PORT` | `8825` | REST 服务端口 |
| `BASE_URL` | `https://qwen-qwen3-tts-demo.ms.show` | 远端 Qwen TTS Gradio 服务地址 |
| `API_KEY` | - | REST API 鉴权密钥（可选） |


## 兼容性说明

- 本项目仍然依赖**远端** Qwen TTS Gradio 服务进行最终音频生成
- 但已经不再依赖**本地** `qwen-tts2api` 仓库、包安装或其进程启动
- Python Skill 默认采用**直连后端**模式
- OpenAI 风格 REST 能力作为**可选暴露层**保留
- 当前实现**不会在运行时自动安装依赖**；缺少 REST 依赖时会直接给出明确提示，要求先完成安装

## 许可证

[Apache-2.0](LICENSE)
