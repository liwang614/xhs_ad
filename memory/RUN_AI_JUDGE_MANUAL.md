# 手动执行 AI 判定（数据库）

## API Key 规则

API Key 不填在 `config.json`，使用环境变量。

优先级：

1. `LLM_API_KEY`（最高优先）
2. 若不存在，再按 provider 读取：
   - `openai` -> `OPENAI_API_KEY`
   - `gemini` -> `GEMINI_API_KEY`
   - `claude` -> `ANTHROPIC_API_KEY`

## 在 config.json 切换判定表

位置：`ai_judge.tables`

1. 单表（字符串写法）：

```json
{
  "ai_judge": {
    "tables": "xhs_note"
  }
}
```

2. 单表（数组写法）：

```json
{
  "ai_judge": {
    "tables": ["xhs_note"]
  }
}
```

3. 多表（数组写法）：

```json
{
  "ai_judge": {
    "tables": ["xhs_note", "xhs_note_backup", "xhs_note_2026"]
  }
}
```

说明：

- `tables` 既支持字符串也支持字符串数组。
- 手动脚本会按 `tables` 顺序逐个表执行判定。

## 在 config.json 直接修改提示词

位置：`ai_judge.note_prompt_template`、`ai_judge.comment_prompt_template`

变量占位符：

- `{{title}}`：标题（评论表一般为空）
- `{{content}}`：正文/评论内容

示例：

```json
{
  "ai_judge": {
    "note_prompt_template": "判断是否求助。标题：{{title}}\\n正文：{{content}}\\n只输出 {\"is_help_post\":0或1}",
    "comment_prompt_template": "判断评论是否求助。评论：{{content}}\\n只输出 {\"is_help_post\":0或1}"
  }
}
```

## 手动执行步骤（项目根目录）

```bash
cd /home/wangli/Projects/xhs_ad
source .venv/bin/activate

# 1) 数据库连接
export MYSQL_DB_HOST=127.0.0.1
export MYSQL_DB_PORT=3306
export MYSQL_DB_USER=root
export MYSQL_DB_PWD=123456
export MYSQL_DB_NAME=media_crawler

# 2) 选一个 key 方式
export LLM_API_KEY=你的key
# 或者：export OPENAI_API_KEY=你的key
# 或者：export GEMINI_API_KEY=你的key
# 或者：export ANTHROPIC_API_KEY=你的key

# 3) 配置 provider/model（在 config.json 的 ai_judge 里）
# mode 建议设为 manual

# 4) 手动跑判定
python tools/classify_help_posts.py --batch-size 50
```

## 行为说明

1. 只处理 `ai_judge.tables` 指定表中 `is_help_post IS NULL` 的记录。
2. 成功写 `0/1`。
3. 失败保持 `NULL`。
4. 失败日志位置：`logs/help_post_judge_errors.log`。

## 验证 SQL

```sql
SHOW COLUMNS FROM xhs_note LIKE 'is_help_post';

SELECT
  SUM(is_help_post = 1) AS help_yes,
  SUM(is_help_post = 0) AS help_no,
  SUM(is_help_post IS NULL) AS help_null
FROM xhs_note;
```
