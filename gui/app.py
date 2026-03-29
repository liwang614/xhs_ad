from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import streamlit as st

from modules.database_store import DatabaseStore

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_store() -> DatabaseStore:
    if "db_store" not in st.session_state:
        st.session_state["db_store"] = DatabaseStore()
    return st.session_state["db_store"]


def _fetch_records(
    store: DatabaseStore,
    table_name: str,
    is_help_post_filter: str,
    opportunity_type_filter: str,
    follow_up_filter: str,
    sort_by_score: bool,
    limit: int,
) -> list[dict]:
    columns = store._get_table_columns(table_name)
    title_col = store._pick_existing_column(columns, ("title", "note_title"))
    content_col = store._pick_existing_column(columns, ("desc", "content", "text", "comment", "body"))
    uid_col = store._pick_existing_column(columns, ("user_id", "uid", "author_id", "comment_user_id"))

    title_expr = f"`{title_col}`" if title_col else "''"
    content_expr = f"`{content_col}`" if content_col else "''"
    uid_expr = f"`{uid_col}`" if uid_col else "''"

    where_parts: list[str] = []
    params: list[object] = []

    if is_help_post_filter == "1":
        where_parts.append("is_help_post=1")
    elif is_help_post_filter == "0":
        where_parts.append("is_help_post=0")
    elif is_help_post_filter == "NULL":
        where_parts.append("is_help_post IS NULL")

    if opportunity_type_filter != "all":
        where_parts.append("opportunity_type=%s")
        params.append(opportunity_type_filter)

    if follow_up_filter != "all":
        if follow_up_filter == "NULL":
            where_parts.append("(follow_up_status IS NULL OR follow_up_status='pending')")
        else:
            where_parts.append("follow_up_status=%s")
            params.append(follow_up_filter)

    where_clause = " AND ".join(where_parts) if where_parts else "1=1"
    order = "lead_score DESC" if sort_by_score else "id DESC"

    # Check which analysis columns actually exist to avoid SQL errors.
    analysis_cols = {
        "opportunity_type": "opportunity_type",
        "opportunity_summary": "opportunity_summary",
        "demand_reason": "demand_reason",
        "lead_score": "lead_score",
        "manual_reply_suggestion": "manual_reply_suggestion",
        "analysis_status": "analysis_status",
        "analyzed_at": "analyzed_at",
        "follow_up_status": "follow_up_status",
        "is_help_post": "is_help_post",
    }
    select_parts = [
        "id",
        f"{title_expr} AS title",
        f"{content_expr} AS content",
        f"{uid_expr} AS commenter_uid",
    ]
    for col in analysis_cols:
        if col in columns:
            select_parts.append(f"`{col}`")
        else:
            select_parts.append(f"NULL AS `{col}`")

    sql = f"""
    SELECT {', '.join(select_parts)}
    FROM `{table_name}`
    WHERE {where_clause}
    ORDER BY {order}
    LIMIT %s
    """
    params.append(limit)

    with store._conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
        col_names = [d[0] for d in cur.description]

    return [dict(zip(col_names, row)) for row in rows]


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="商业机会分析台", layout="wide")
    st.title("商业机会分析台")

    store = _get_store()

    # --- Sidebar filters ---
    with st.sidebar:
        st.header("筛选条件")
        tables = st.text_input("目标表", value="xhs_note_comment")
        table_name = tables.strip() or "xhs_note_comment"

        is_help = st.selectbox("is_help_post", ["all", "1", "0", "NULL"], index=0)
        opp_type = st.selectbox(
            "opportunity_type",
            ["solution_request", "all", "none"],
            index=0,
        )
        follow_up = st.selectbox(
            "follow_up_status",
            ["all", "NULL", "pending", "contacted", "ignored"],
            index=0,
        )
        sort_score = st.checkbox("按 lead_score 降序", value=True)
        limit = st.slider("显示条数", 10, 500, 100)

    # --- Fetch ---
    try:
        records = _fetch_records(
            store,
            table_name=table_name,
            is_help_post_filter=is_help,
            opportunity_type_filter=opp_type,
            follow_up_filter=follow_up,
            sort_by_score=sort_score,
            limit=limit,
        )
    except Exception as exc:
        st.error(f"查询失败: {exc}")
        return

    st.caption(f"共 {len(records)} 条记录")

    if not records:
        st.info("没有符合条件的记录")
        return

    # --- Display ---
    for rec in records:
        row_id = rec.get("id")
        title = rec.get("title") or ""
        content = rec.get("content") or ""
        uid = rec.get("commenter_uid") or ""
        opp = rec.get("opportunity_type") or ""
        summary = rec.get("opportunity_summary") or ""
        reason = rec.get("demand_reason") or ""
        score = rec.get("lead_score")
        suggestion = rec.get("manual_reply_suggestion") or ""
        status = rec.get("analysis_status") or ""
        follow = rec.get("follow_up_status") or "pending"
        hp = rec.get("is_help_post")

        score_display = f"**{score}**" if score is not None else "-"
        hp_display = str(hp) if hp is not None else "NULL"

        with st.expander(f"#{row_id}  |  score={score if score is not None else '-'}  |  {opp}  |  {title[:60]}"):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown(f"**原文内容**\n\n{content[:1000]}")
                if summary:
                    st.markdown(f"**机会摘要**: {summary}")
                if reason:
                    st.markdown(f"**判定理由**: {reason}")
                if suggestion:
                    st.markdown(f"**建议回复话术**: {suggestion}")
            with col2:
                st.markdown(f"**is_help_post**: {hp_display}")
                st.markdown(f"**opportunity_type**: {opp}")
                st.markdown(f"**lead_score**: {score_display}")
                st.markdown(f"**评论者 UID**: {uid or '(空)'}")
                st.markdown(f"**分析状态**: {status or '(未分析)'}")

                new_status = st.selectbox(
                    "跟进状态",
                    ["pending", "contacted", "ignored"],
                    index=["pending", "contacted", "ignored"].index(follow) if follow in ("pending", "contacted", "ignored") else 0,
                    key=f"follow_{row_id}",
                )
                if new_status != follow:
                    try:
                        store.update_follow_up_status(row_id, new_status, table_name=table_name)
                        st.success(f"已更新为 {new_status}")
                    except Exception as exc:
                        st.error(f"更新失败: {exc}")


if __name__ == "__main__":
    main()
