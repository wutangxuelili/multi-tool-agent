"""公司员工库的只读查询工具。

安全设计（三层）：
1. 语句层：只允许单条 SELECT（挡掉明显的手滑/注入尝试）；
2. 连接层：用 `file:...?mode=ro` 只读 URI 打开——即使语句层校验被绕过，
   数据库层也写不进去。真正的保护是这一层；
3. 数据分级：`salary` 这类敏感列**默认脱敏**，需要在受控环境下
   显式设置 `DB_SHOW_SALARY=1` 才返回真实值（生产应由权限系统决定，而不是靠环境变量）。
"""

import os
import sqlite3

from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from tools import db_config

load_dotenv()

# 单次最多返回的行数
MAX_ROWS = 20

# 敏感列的识别关键词（列名包含即视为敏感）
SENSITIVE_COLUMN_KEYWORDS = ("salary", "薪", "工资")
MASK = "***"


class DatabaseArgs(BaseModel):
    sql: str = Field(
        min_length=1,
        description="要执行的 SQL 查询语句，必须是 SELECT 开头",
    )


def _connect_readonly() -> sqlite3.Connection:
    """以只读模式打开数据库（路径在调用时读取，便于测试替换）。"""
    conn = sqlite3.connect(f"file:{db_config.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def sensitive_columns_allowed() -> bool:
    """当前环境是否被授权查看敏感列（默认不授权）。"""
    return os.getenv("DB_SHOW_SALARY", "").strip().lower() in {"1", "true", "yes", "on"}


def is_sensitive_column(name: str) -> bool:
    lowered = name.lower()
    return any(keyword in lowered for keyword in SENSITIVE_COLUMN_KEYWORDS)


@tool(args_schema=DatabaseArgs)
def query_database(sql: str) -> str:
    """查询公司数据库，返回员工信息。只支持 SELECT 查询，最多返回 20 行。"""
    # 1. 安全校验：只允许单条 SELECT
    stripped = sql.strip().rstrip(";")
    if not stripped.upper().startswith("SELECT"):
        return "错误：只允许 SELECT 查询，不允许修改数据。"
    if ";" in stripped:
        return "错误：不允许多条 SQL 语句。"

    # 2. 数据库是否存在（给出可操作的提示，而不是 SQLite 的原始报错）
    if not db_config.DB_PATH.exists():
        return (
            f"错误：数据库不存在（{db_config.DB_PATH}）。"
            "请先运行 python scripts/init_db.py 初始化。"
        )

    # 3. 只读连接 + 查询（连接用 finally 关闭，异常路径也不泄漏）
    try:
        conn = _connect_readonly()
    except sqlite3.Error as e:
        return f"错误：无法打开数据库（{db_config.DB_PATH}）：{e}"

    try:
        rows = conn.execute(stripped).fetchmany(MAX_ROWS)
    except sqlite3.Error as e:
        return f"SQL 执行失败：{e}"
    finally:
        conn.close()

    if not rows:
        return "查询没有返回任何结果。"

    # 4. 格式化返回（敏感列默认脱敏）
    columns = list(rows[0].keys())
    masked = (
        []
        if sensitive_columns_allowed()
        else [c for c in columns if is_sensitive_column(c)]
    )

    lines = [" | ".join(columns), "-" * 40]
    for row in rows:
        lines.append(
            " | ".join(
                MASK if col in masked else str(row[col]) for col in columns
            )
        )
    output = "\n".join(lines)

    if masked:
        output += (
            f"\n\n（敏感列已脱敏：{', '.join(masked)}。"
            "默认不返回真实值，受控环境可设置 DB_SHOW_SALARY=1 授权查看。）"
        )

    return output
