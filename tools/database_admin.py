import sqlite3

from langchain_core.tools import tool
from pydantic import BaseModel, Field

DB_PATH = "data/company.db"


class DeleteArgs(BaseModel):
    employee_id: int = Field(description="要删除的员工 ID")


@tool(args_schema=DeleteArgs)
def delete_employee(employee_id: int) -> str:
    """删除指定 ID 的员工。"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM employees WHERE id = ?", (employee_id,))
    conn.commit()
    affected = cursor.rowcount
    conn.close()
    if affected == 0:
        return f"未找到 ID 为 {employee_id} 的员工。"
    return f"已删除 ID 为 {employee_id} 的员工。"
