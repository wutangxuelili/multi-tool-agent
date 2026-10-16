"""敏感工具：删除员工。

这个函数本身"能删"，但**不会被 Agent 直接执行**：
`agent/nodes.py` 的 `_execute_tool` 会拒绝未经人工确认的敏感工具调用
（登记表在 `tools/__init__.py` 的 SENSITIVE_TOOL_NAMES）。
真正的闸门在执行层，不依赖提示词自觉。

数据安全：删除是**先归档再删除**（同一个事务）——被删的行连同
删除时间与操作人一起写进 `deleted_employees` 表，可追溯、可回滚；
操作人由 `confirm_node` 通过 `utils/operator.py` 的 ContextVar 传入。
"""

import sqlite3
from datetime import datetime

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools import db_config
from utils.operator import get_operator

ARCHIVE_TABLE = "deleted_employees"


class DeleteArgs(BaseModel):
    employee_id: int = Field(description="要删除的员工 ID")


def _ensure_archive_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ARCHIVE_TABLE} (
            id INTEGER NOT NULL,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            salary INTEGER NOT NULL,
            hire_date TEXT NOT NULL,
            deleted_at TEXT NOT NULL,
            deleted_by TEXT
        )
        """
    )


@tool(args_schema=DeleteArgs)
def delete_employee(employee_id: int) -> str:
    """删除指定 ID 的员工（先归档到 deleted_employees，再删除）。"""
    db_path = db_config.DB_PATH  # 调用时读取，便于测试替换

    if not db_path.exists():
        return (
            f"删除失败：数据库不存在（{db_path}）。"
            "请先运行 python scripts/init_db.py 初始化。"
        )

    operator = get_operator()
    conn = sqlite3.connect(db_path)
    try:
        # with conn 只管理事务：任一步失败自动回滚（不会删了却没归档）
        with conn:
            _ensure_archive_table(conn)
            row = conn.execute(
                "SELECT id, name, department, salary, hire_date"
                " FROM employees WHERE id = ?",
                (employee_id,),
            ).fetchone()
            if row is None:
                return f"未找到 ID 为 {employee_id} 的员工。"

            conn.execute(
                f"INSERT INTO {ARCHIVE_TABLE}"
                " (id, name, department, salary, hire_date, deleted_at, deleted_by)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (*row, datetime.now().isoformat(timespec="seconds"), operator),
            )
            affected = conn.execute(
                "DELETE FROM employees WHERE id = ?", (employee_id,)
            ).rowcount
    except sqlite3.Error as e:
        return f"删除失败：{e}"
    finally:
        conn.close()

    if affected == 0:
        return f"未找到 ID 为 {employee_id} 的员工。"
    return (
        f"已删除 ID 为 {employee_id} 的员工。"
        f"（已归档到 {ARCHIVE_TABLE}，操作人：{operator or '未知'}）"
    )
