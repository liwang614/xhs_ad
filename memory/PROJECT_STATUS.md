# 项目状态记录

更新时间：2026-02-19

## 已落地的 AI 求助帖判定能力

1. 支持提供方：`openai`、`gemini`、`claude`
2. API Key 读取优先级：
   - `LLM_API_KEY`（最高优先）
   - `OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`
3. 数据库字段：
   - `xhs_note.is_help_post`（`TINYINT NULL`）
4. 判定表切换：
   - `config.json` -> `ai_judge.tables`
   - 支持单表与多表
5. 判定失败策略：
   - 保持 `is_help_post=NULL`
   - 记录错误日志到 `logs/help_post_judge_errors.log`

## 相关入口

1. 手动批量判定脚本：`tools/classify_help_posts.py`
2. 判定核心模块：`modules/help_post_judge.py`
3. 数据库读写接口：`modules/database_store.py`
4. 配置入口：`config.json` 下 `ai_judge`，解析在 `modules/config_loader.py`
