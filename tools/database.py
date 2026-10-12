import os  # noqa: F401
import sqlite3

from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

load_dotenv()

DB_PATH = "data/company.db"


class DatabaseArgs(BaseModel):
    sql: str = Field(
        min_length=1,
        description="要执行的 SQL 查询语句，必须是 SELECT 开头",
    )


@tool(args_schema=DatabaseArgs)
def query_database(sql: str) -> str:
    """查询公司数据库，返回员工信息。只支持 SELECT 查询，最多返回 20 行。"""
    # 1. 安全校验：只允许 SELECT
    stripped = sql.strip().rstrip(";")
    if not stripped.upper().startswith("SELECT"):
        return "错误：只允许 SELECT 查询，不允许修改数据。"

    # 2. 禁止多条语句
    if ";" in stripped:
        return "错误：不允许多条 SQL 语句。"

    # 3. 只读连接
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(stripped)
        rows = cursor.fetchmany(20)
        conn.close()
    except sqlite3.OperationalError as e:
        return f"SQL 执行失败：{e}"

    if not rows:
        return "查询没有返回任何结果。"

    # 4. 格式化返回
    columns = rows[0].keys()
    lines = [" | ".join(columns), "-" * 40]
    for row in rows:
        lines.append(" | ".join(str(row[col]) for col in columns))

    return "\n".join(lines)


if __name__ == "__main__":
    print(query_database.invoke({"sql": "SELECT * FROM employees"}))
    print("\n--- 按部门筛选 ---")
    print(
        query_database.invoke(
            {"sql": "SELECT name, salary FROM employees WHERE department = '技术部'"}
        )
    )
    print("\n--- 非法查询测试 ---")
    print(query_database.invoke({"sql": "DROP TABLE employees"}))
