# AI 私厨 Agent

[在线 Demo](https://ai-personal-chef.onrender.com) · [健康检查](https://ai-personal-chef.onrender.com/api/health)

一个支持食材图片识别、联网菜谱搜索、多轮会话记忆和 SSE 流式输出的多模态 AI 私厨。

## 主要功能

- 上传 JPG、PNG 或 WebP 食材图片，由多模态模型识别可以确认的食材。
- LangGraph Agent 根据任务自主使用 Tavily 搜索菜谱资料。
- 生成包含参考用量、火候、时间、详细步骤和食品安全提醒的菜谱。
- 使用 SQLite Checkpointer 按 `thread_id` 保存多轮对话状态。
- FastAPI 通过 SSE 将模型内容流式返回浏览器。
- 前端安全渲染常用 Markdown，支持历史恢复、图片预览和新建会话。

## 技术栈

- Python、FastAPI、Pydantic
- LangChain、LangGraph、通义千问 OpenAI 兼容接口
- Tavily Search
- SQLite / `AsyncSqliteSaver`
- HTML、CSS、JavaScript、Server-Sent Events

## 请求链路

```text
浏览器选择图片或输入食材
        ↓
JavaScript 将图片转换为 Base64 Data URL
        ↓
POST /api/v1/chat/stream
        ↓
Pydantic 校验文字、会话 ID、图片格式和大小
        ↓
LangGraph Agent 分析任务并按需调用 Tavily
        ↓
SQLite Checkpointer 保存会话状态
        ↓
FastAPI 使用 SSE 流式返回状态和回答
        ↓
浏览器安全渲染 Markdown
```

## 本地运行

项目使用 [uv](https://docs.astral.sh/uv/) 管理 Python 环境。

```powershell
uv sync
Copy-Item .env.example .env
```

打开 `.env`，填入自己的阿里云百炼和 Tavily API Key。不要把 `.env` 提交到 Git。

启动服务：

```powershell
uv run python -m app.main
```

打开：

- 网页：<http://127.0.0.1:8001/>
- API 文档：<http://127.0.0.1:8001/docs>
- 健康检查：<http://127.0.0.1:8001/api/health>

### Docker 运行

Docker Compose 会读取本地 `.env`，并用命名卷保存 SQLite 会话数据：

```powershell
docker compose up --build
```

打开 <http://127.0.0.1:8001/>。生产镜像以非 root 用户运行，并内置 `/api/health` 容器健康检查。

## 自动化测试

自动化测试不会请求模型和 Tavily，也不会消耗 API 额度：

```powershell
uv run python -m unittest discover -s tests -v
```

GitHub Actions 会在每次 push 和 pull request 时运行全部单元测试并构建生产 Docker 镜像。

需要真实 API Key 的手动连通性检查位于 `scripts/`：

```powershell
uv run python -m scripts.test_model
uv run python -m scripts.test_tavily
uv run python -m scripts.test_agent
uv run python -m scripts.test_memory
```

## Agent 评测

[`evals/cases.jsonl`](evals/cases.jsonl) 包含 40 条固定用例：8 条公开图片识别、8 条文字食材确认、16 条常规菜谱和 8 条食品安全场景。评测报告包含：

- 食材识别的 micro precision、micro recall、micro F1 与整组完全匹配率；
- Tavily 工具调用成功率与应搜索场景覆盖率；
- 12 项菜谱字段完整率；
- 首 Token 延迟的 mean、median 和 p95。

完整运行会调用模型和 Tavily，并产生 API 费用：

```powershell
uv run python -m evals.run_evals
```

小规模连通性检查：

```powershell
uv run python -m evals.run_evals --limit 3 --skip-images
```

指标口径、公开图片来源和限制见 [`evals/README.md`](evals/README.md)。仓库还提供手动触发的 `Agent evaluations` 工作流；在 GitHub Secrets 配置 `DASHSCOPE_API_KEY` 和 `TAVILY_API_KEY` 后即可运行并下载 JSON 报告。

### 当前基线（2026-07-18，`qwen3.5-plus`）

| 指标 | 结果 |
| --- | ---: |
| 完整用例成功 | 40 / 40 |
| 食材识别 micro F1 | 98.41% |
| 食材整组完全匹配率 | 93.75% |
| Tavily 工具调用成功率 | 100%（24 / 24） |
| 菜谱字段完整率 | 86.11%（21 条适用用例） |
| 首 Token 延迟中位数 / p95 | 9.31 秒 / 13.79 秒 |

精简的机器可读结果保存在 [`evals/baseline.json`](evals/baseline.json)。延迟受本地网络、模型服务负载和搜索耗时影响，不应视为固定 SLA。

## 部署

项目提供 [`render.yaml`](render.yaml)，可以由 Render Blueprint 从 Dockerfile 部署：

1. 将仓库发布到 GitHub，在 Render 新建 Blueprint 并选择该仓库。
2. 首次创建时填写 `DASHSCOPE_API_KEY` 和 `TAVILY_API_KEY`；它们以 `sync: false` 声明，不会写入仓库。
3. 等待 Docker 构建完成，通过 `/api/health` 检查服务状态。

免费实例的文件系统可能在重启或重新部署后重置，因此在线 Demo 的 SQLite 对话历史不应视为永久数据。正式环境应改用持久化数据库或挂载持久磁盘。

## API

### 流式聊天

```http
POST /api/v1/chat/stream
Content-Type: application/json
```

```json
{
  "message": "我有鸡蛋和西红柿，请推荐三道菜",
  "thread_id": "demo-001",
  "image_data": null
}
```

SSE 事件包含：

- `status`：当前处理阶段。
- `token`：新增模型文本。
- `done`：本轮生成完成。
- `error`：本轮生成失败。

### 会话历史

```http
GET /api/v1/chat/messages?thread_id=demo-001
DELETE /api/v1/chat/messages?thread_id=demo-001
```

## 安全与限制

- 图片在学习版本中以 Base64 放入请求体，限制为 5 MB。生产环境应改用对象存储。
- SQLite 适合本地开发和单实例演示；多实例部署建议使用更适合并发的持久化方案。
- 模型可能产生错误内容，涉及过敏、食品安全和健康问题时应人工确认。
- 前端 Markdown 渲染器只支持标题、列表、粗体、行内代码和 HTTP(S) 链接，并通过 DOM API 避免直接注入 HTML。
- 当前记忆是会话状态，不是跨会话用户画像。

## 后续规划

- 增加用户过敏原、忌口和饮食目标的独立偏好存储。
- 增加 Agent 工具调用轨迹与耗时观测。
- 增加食品安全事实正确性和参考链接有效性的模型裁判与人工复核。
- 增加限流、用户鉴权和生产级持久化数据库。
