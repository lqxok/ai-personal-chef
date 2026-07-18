# Agent 评测说明

`cases.jsonl` 包含 40 条固定用例：8 条公开图片识别、8 条文字食材确认、16 条常规菜谱和 8 条食品安全场景。

## 指标定义

- **食材识别正确率**：仅解析回答中“确认的食材”区域，在用例给定候选集上计算 micro precision、micro recall、micro F1 和整组完全匹配率，避免菜谱配料造成假阳性。
- **工具调用成功率**：`on_tool_end` 事件数除以 `on_tool_start` 事件数；另报告应搜索用例中至少完成一次工具调用的覆盖率。
- **菜谱字段完整率**：按菜名、推荐理由、人数、耗时、难度、带单位用量、已有/缺少食材、详细步骤、火候/时间/熟度、失败点/安全、真实链接和烹饪顺序共 12 项规则评分。它衡量格式完整性，不代表口味或事实正确性。对于野生菌、破损鸡蛋、室温久置米饭等应直接拒绝给菜谱的场景，不计算该指标。
- **首 Token 延迟（TTFT）**：从开始执行 Agent 到收到第一个非空模型文本块的时间，报告 mean、median 和 p95。

## 运行

完整评测会调用模型和 Tavily，并产生 API 费用：

```powershell
uv run python -m evals.run_evals
```

先做小规模连通性检查：

```powershell
uv run python -m evals.run_evals --limit 3 --skip-images
```

结果默认写入 `artifacts/eval-results.json`，该目录不提交 Git。公开结果时应同时记录模型名、生成时间、用例数量和失败数量。

评测默认单并发运行，因为所有用例共享一个 SQLite Checkpointer；这能避免并发写入影响稳定性和延迟口径。

[`baseline.json`](baseline.json) 保存最近一次完整运行的精简指标，不包含模型完整回答。完整原始输出写入被 Git 忽略的 `artifacts/`。

## 图片来源

视觉用例通过 Wikimedia Commons 的 `Special:Redirect/file` 获取缩略图，源文件页面如下：

- `Tomato_vegetable.jpg`、`Tomato_(1).jpg`
- `Broccoli_vegetable.jpg`
- `Carrot_vegetable_on_white_background.jpg`
- `Bell_pepper.jpg`、`Green-Bell-Pepper.jpg`
- `Delaware_potatoes_vegetable.jpg`
- `CHICKEN_BREAST.jpg`

这些文件分别采用其 Commons 页面标注的公有领域或 Creative Commons 许可。评测脚本仅在运行时下载，不在仓库中再分发图片。
