# xhs_ad 商业机会分析台 - 使用说明

## 概述

本系统从数据库中已有的小红书消息/评论出发，通过 AI 分析筛选商业机会线索，供人工查看和跟进。

**当前只支持一类机会：`求解决方案`（solution_request）**

## 核心原则

- **默认不自动回复**，人工跟进以降低风险
- `codexexec` 是本地 CLI 分析后端
- GUI 只监听 `127.0.0.1:12700`，不暴露公网
- 数据源来自数据库中的现有消息/评论，不按关键词抓取后自动回复

## 默认工作流

```
1. 运行批量分析
   python tools/analyze_business_opportunities.py

2. 启动 GUI 查看结果
   python tools/run_gui.py

3. 浏览器访问 http://127.0.0.1:12700
   - 按 lead_score 排序
   - 按 opportunity_type 过滤
   - 查看原文、分析理由、建议话术
   - 人工标记跟进状态 (pending / contacted / ignored)

4. 人工决定是否跟进（系统不会自动回复）
```

## 命令参考

### 批量分析

```bash
# 使用默认配置
python tools/analyze_business_opportunities.py

# 指定批量大小
python tools/analyze_business_opportunities.py --batch-size 50

# 指定目标表
python tools/analyze_business_opportunities.py --tables xhs_note,xhs_note_comment

# 重新分析全部记录（含已分析）
python tools/analyze_business_opportunities.py --all
```

### 启动 GUI

```bash
python tools/run_gui.py
# 默认: http://127.0.0.1:12700
```

### 旧流程（已默认停用）

旧的"搜索关键词 → AI判定 → 生成文案 → MCP自动回复"流程仍保留在代码中，但默认不触发：

- `config.json` 中 `search.keywords` 为空列表
- `ai_judge.generate_reply_mode` 为 `"manual"`

如需手动触发旧流程：

```bash
# 仅判定 is_help_post
python tools/classify_help_posts.py

# 仅生成文案（不回复）
python tools/generate_and_reply_help_comments.py --mode generate

# 手动回复指定记录
python tools/generate_and_reply_help_comments.py --mode reply --reply-ids 1,2,3
```

## 配置说明 (config.json)

### analysis 段（新主流程）

| 字段 | 默认值 | 说明 |
|------|--------|------|
| enabled | true | 是否启用分析 |
| provider | "codexexec" | 分析 provider 名称 |
| command | "codexexec" | CLI 命令路径 |
| timeout | 120 | 单条分析超时(秒) |
| batch_size | 20 | 每批处理条数 |
| tables | ["xhs_note_comment"] | 目标数据表 |

### 其他段保持不变

- `search` / `execution` / `comment_mode` — 旧搜索+评论流程
- `ai_judge` — 旧 AI 判定配置
- `mcp` — MCP 回复配置（保留，默认不触发）

## 数据库字段

分析结果写入以下字段（自动迁移，无需手动建表）：

| 字段 | 说明 |
|------|------|
| is_help_post | 0/1 是否有需求 |
| opportunity_type | solution_request / none |
| opportunity_summary | 机会摘要 |
| demand_reason | 判定理由 |
| lead_score | 线索评分 0-100 |
| manual_reply_suggestion | 建议人工回复话术 |
| analysis_status | done / failed / NULL(待分析) |
| analyzed_at | 分析完成时间 |
| follow_up_status | pending / contacted / ignored |
