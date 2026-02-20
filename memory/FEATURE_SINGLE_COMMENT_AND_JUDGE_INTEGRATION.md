# 功能说明：单条文案存储 + AI判定脚本集成

更新时间：2026-02-19

## 功能目标

1. 只处理 `is_help_post = 1` 的记录。
2. 评论文案只保留单条，不再区分“生成文案/发送文案”两列。
3. `tools/classify_help_posts.py` 既可单独运行，也可被 `main.py` 复用。

## 当前行为

1. 主流程在可选判定后，若 `is_help_post != 1` 直接跳过。
2. 主流程“发送动作”会写 `interactions`，并把单条评论文案回写到 `xhs_note_comment.generated_comment_content`。
3. 启动时会自动迁移 `xhs_note_comment`：
   - 确保 `is_help_post` 和 `generated_comment_content` 存在。
   - 将旧 `sent_comment_content` 合并进 `generated_comment_content` 后删除。
   - 列顺序调整为 `content -> is_help_post -> generated_comment_content`。

## 代码位置

1. 主流程过滤与入库：`main.py`
2. 单条评论决策：`modules/logic_processor.py`
3. 数据库迁移与回写：`modules/database_store.py`
4. 配置解析（judge_model / generate_model）：`modules/config_loader.py`
5. 可复用批量判定函数与脚本入口：`tools/classify_help_posts.py`

## 启动方式

1. 单独测试判定功能：
   - `.venv/bin/python tools/classify_help_posts.py --config config.json --batch-size 50`
2. 集成主流程整体启动（`ai_judge.mode=batch` 时触发批量判定）：
   - `.venv/bin/python main.py`

## 环境变量

建议使用 `.env` 统一管理：

1. MySQL：`MYSQL_DB_HOST` `MYSQL_DB_PORT` `MYSQL_DB_USER` `MYSQL_DB_PWD` `MYSQL_DB_NAME`
2. 表名：`MYSQL_NOTE_TABLE` `MYSQL_HISTORY_TABLE` `MYSQL_NOTE_COMMENT_TABLE`
3. AI Key：`LLM_API_KEY` 或 provider 专属 key（`OPENAI_API_KEY` / `GEMINI_API_KEY` / `ANTHROPIC_API_KEY`）
