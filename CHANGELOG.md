# Changelog

本文件记录项目的显著变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循[语义化版本](https://semver.org/lang/zh-CN/)。

## [0.3.1] - 2026-09-09

针对 [issue #1](https://github.com/RusianHu/qwen-tts-skill/issues/1)（v0.3.1 hardening）
的安全加固与规范合规版本。无新功能。

### ⚠️ 破坏性变更

- **本地 REST 密钥与上游凭据拆分**（修复凭据边界违规）
  此前同一个 `API_KEY` 既保护本地 `127.0.0.1` 服务、又作为 `Authorization: Bearer`
  发给第三方上游——为保护本地端口设置的密码会泄露给远端。现拆分为：
  - `QWEN_TTS_REST_API_KEY`：只保护本地 REST 服务，**绝不**离开本机
  - `QWEN_TTS_UPSTREAM_API_KEY`：仅在访问需鉴权的上游时发送
  - 旧变量 `API_KEY` 降级为 `QWEN_TTS_REST_API_KEY` 的别名（打印废弃告警），
    **任何情况下都不再发送给上游**
- **REST 服务默认只监听 `127.0.0.1`**（此前为 `0.0.0.0`），CORS 默认关闭
  （此前 `allow_origins=["*"]`）。暴露到局域网需显式设置 `HTTP_HOST=0.0.0.0`
  与 `QWEN_TTS_CORS_ORIGINS`
- **删除无效公开参数**：`QwenTTSSkill.synthesize(api_key=...)`、
  `skill_say/skill_voices/skill_languages` 的 `port` 参数此前被静默忽略，现已移除
- **许可证声明修正**：`LICENSE` 文件实为 Apache-2.0 但 `pyproject.toml`/`README` 声明
  MIT，现按项目意图统一为 **MIT**（LICENSE 文件已更换为 MIT 文本）
- **`skill_say` 返回语义**：未指定 `output_path` 时不再丢失音频，返回 base64 data URI

### 修复

- **FastAPI 不再阻塞 event loop**：`/v1/audio/speech` 路由由 `async def` 改为同步 `def`，
  合成期间 `/health` 等路由可正常响应（此前同步阻塞调用会卡住整个 event loop）
- **catalog 刷新不再故障放大**：上游不可用时，此前一次合成请求会在多个 resolver 中
  重复触发 catalog 刷新（随重试倍增）。现收敛为每次尝试最多一次，失败后
  30 秒（`CATALOG_FAILURE_TTL`）内不再探测
- **catalog 空结果不再视为成功**：解析结果为空时返回失败并**保留旧缓存**，
  不再用空数据覆盖有效的音色/语言列表
- **CLI 失败返回非零退出码**（此前恒为 0）：`0` 成功 / `1` 运行失败 / `2` 参数错误 /
  `3` 配置依赖错误；新增 `--json` 供 Agent 稳定解析；`--say` 与 `--list-*` 互斥
- **`QwenTTSService.synthesize()` 自动携带实例 REST key**：服务启用鉴权时不再自请求 401
- **服务子进程不再用无人消费的 PIPE**：改用 `DEVNULL`，避免日志写满 pipe buffer 阻塞子进程；
  启动超时/失败路径统一清理子进程（terminate → wait → kill → wait），不再残留占端口进程
- **环境变量解析加防御**：`QWEN_TTS_MAX_ATTEMPTS` / `QWEN_TTS_RETRY_DELAY` / `HTTP_PORT`
  非法值回退默认并告警，不再在构造/import 阶段抛异常
- **文档表述修正**：不再承诺「改 `BASE_URL` 即可调用 ModelScope / DashScope REST API」
  （实现仅支持 Gradio-compatible 上游）；「OpenAI-compatible」收敛为
  `/v1/audio/speech` 兼容子集；`SKILL.md` 命令示例补充含空格路径的引号写法

### 新增

- **Agent Skills 规范合规**：`SKILL.md` 的 `name` 改为 `qwen-tts-skill`，
  与原样克隆的分发目录名一致；frontmatter 增加 `license: MIT`
- **凭据边界 / 许可证一致性 / skill name 匹配 / CLI 退出码自动测试**
- **GitHub Actions CI**（`.github/workflows/ci.yml`）：Linux + Windows ×
  Python 3.10–3.13，运行 pytest（离线）、verify.py 与发布一致性校验；
  真实上游冒烟单独隔离

## [0.3.0] - 2026-09-09

### ⚠️ 破坏性变更

- **默认上游服务已更换**
  原默认上游 `https://qwen-qwen3-tts-demo.ms.show` 已停止服务（HTTP 403，官方提示改走需
  ModelScope token 的 `api-inference` 地址）。默认上游改为
  `https://qwen-qwen3-tts-demo.hf.space`，其 `/tts_interface` 参数签名与原上游一致，
  输出同为 24kHz / 单声道 / 16bit WAV，免鉴权，提供 49 个音色、11 种语言。
  旧地址保留为 `LEGACY_UPSTREAM_URL` 常量仅供诊断。

- **`language` 参数行为修正**
  此前传入 `zh` / `en` 等两字母代码**不会生效**（上游实际使用 `chinese` / `english` 全拼），
  且会静默回退为 `auto` 而不报错。现已加入别名映射，文档承诺的 `zh` / `en` / `ja` 等可正常使用。
  若你此前依赖"传 `zh` 等于 `auto`"这一行为，请注意其已改变。

- **`pydantic` 不再为核心依赖**
  此前 `pydantic` 在模块顶层导入，导致仅做语音合成也需安装 Web 框架栈。现已改为延迟导入，
  核心能力（`--say` / `--list-voices` / `--list-languages` / Python API）只需
  `requests` 与 `gradio_client`；`fastapi` / `uvicorn` / `pydantic` 仅启动 REST 服务时需要。

### 修复

- **上游不可达不再导致崩溃**
  `Client` 构造此前位于 `try` 块之外（`refresh_catalog()` 与 `synthesize()` 两处），
  上游超时或失效时异常直接冒泡，造成 CLI 崩溃、FastAPI lifespan 失败导致**服务完全起不来**。
  现已纳入异常处理：上游不可用时 REST 服务仍可启动，`/health` 返回 200 且缓存计数为 0，
  `synthesize()` 返回 `success=False` 而非抛异常。

- **`api_key` 此前从未生效**
  `_create_client()` 只调用 `Client(upstream_url)`，构造参数中保存的 `api_key` 从未用于鉴权。
  现已作为 `Authorization: Bearer` 请求头透传给上游。

- **音色匹配容错**
  上游存在 `Ono Anna` / `Radio Gol` / `Eldric Sage` 等带空格的音色 ID。
  现已忽略大小写与分隔符差异，`ono-anna` / `onoanna` / `Ono Anna` 均可正确命中。

- **缺依赖时给出可操作提示**
  全新环境此前只会抛出裸的 `ModuleNotFoundError`。现在作为脚本运行时会预检核心依赖，
  缺失时打印 `pip install -r requirements.txt` 指引并以退出码 1 结束。

- **CLI 输出不再被污染**
  gradio_client 会向 stdout 打印 `Loaded as API: ...`（单次合成最多两行），
  干扰程序化解析。已通过 `verbose=False` 抑制。

- **文档修正**
  - 移除 `AGENTS.md` 中已失效且危险的 `python -m qwen_tts`（会启动外部废弃项目且挂起不退）
  - 修正 `SKILL.md` 中过时的函数行号引用
  - 命令示例统一改为 `<SKILL_DIR>` 绝对路径写法（相对路径在其他工作目录会失败）
  - frontmatter 描述修正：实际支持 10 种语言而非仅中英；输出为 WAV 而非"OpenAI 兼容格式"

### 新增

- **上游抖动自动重试**：新增 `QWEN_TTS_MAX_ATTEMPTS`（默认 `3`）与
  `QWEN_TTS_RETRY_DELAY`（默认 `2` 秒，按次数递增）。托管型 Space 实测偶发失败约 2%，
  重试可直接兜住。
- **依赖预检与分层说明**：`CORE_REQUIRED_PACKAGES` / `REST_REQUIRED_PACKAGES` 分离。
- **真实上游冒烟测试**：默认跳过，设置 `QWEN_TTS_NETWORK_TESTS=1` 开启。
- **发布一致性测试**：校验 `pyproject.toml` 与 `__version__` 不漂移。
- **本 CHANGELOG 文件**。

### 已知限制

- 上游为免费 HuggingFace Space：短文本约 10-15 秒，1000 字约 6 分钟，且可能休眠冷启动。
- 当前为单上游架构，无自动降级。上游若失效需手动修改 `BASE_URL`
  （例如改用 ModelScope 官方 API 并配置 `API_KEY`，代码已支持鉴权透传）。

## [0.2.1] - 2026-04-10

- 发布自包含 skill 版本，不再依赖外部 `qwen-tts2api` 项目。

[0.3.1]: https://github.com/RusianHu/qwen-tts-skill/releases/tag/v0.3.1
[0.3.0]: https://github.com/RusianHu/qwen-tts-skill/releases/tag/v0.3.0
[0.2.1]: https://github.com/RusianHu/qwen-tts-skill/releases/tag/v0.2.1
