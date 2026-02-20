# 故障修复记录：`Unknown column 'title' in 'field list'`

## 报错现象

运行命令：

```bash
python tools/classify_help_posts.py
```

出现错误（核心）：

```text
pymysql.err.OperationalError: (1054, "Unknown column 'title' in 'field list'")
```

## 根因

`config.json` 中目标表配置为：

```json
"ai_judge": {
  "tables": ["xhs_note_comment"]
}
```

但旧实现固定查询：

```sql
SELECT id, title, `desc` FROM <table> ...
```

而 `xhs_note_comment` 表实际字段是 `content`（没有 `title`），导致 SQL 报错。

## 已做修复

已修改 `modules/database_store.py`，将待判定数据查询改为“按表结构自动识别文本列”：

1. 新增表字段探测：
   - `_get_table_columns`
   - `_pick_existing_column`
2. 在 `fetch_pending_help_posts` 中动态选择列：
   - 标题列候选：`title` / `note_title`
   - 内容列候选：`desc` / `content` / `text` / `comment` / `body`
3. 若表无可用文本列，抛出明确错误提示（而不是 SQL 语法报错）。

## 验证结果

已验证以下两张表均可正常读取待判定数据：

- `xhs_note`
- `xhs_note_comment`

即：不再触发 `Unknown column 'title'`。

## 使用建议

1. 只判定帖子：

```json
"tables": ["xhs_note"]
```

2. 帖子 + 评论一起判定：

```json
"tables": ["xhs_note", "xhs_note_comment"]
```

3. 执行命令：

```bash
python tools/classify_help_posts.py
```

