"""数据库工具的单元测试。

前提：data/company.db 已存在（CI 里由 workflow 先执行 scripts/inint_db.py 生成）。
"""

from tools.database import query_database


def test_count_employees():
    """应有 7 名员工（按 inint_db.py 的初始数据）。"""
    result = query_database.invoke({"sql": "SELECT COUNT(*) AS n FROM employees"})
    # 结果格式类似 "n\n---\n7"
    assert "7" in result


def test_query_by_department():
    """技术部应有张三、李四、周八。"""
    result = query_database.invoke(
        {"sql": "SELECT name FROM employees WHERE department = '技术部'"}
    )
    assert "张三" in result
    assert "李四" in result
    assert "周八" in result


def test_non_select_is_rejected():
    """非 SELECT 语句应被拒绝。"""
    result = query_database.invoke({"sql": "DROP TABLE employees"})
    assert "只允许 SELECT" in result or "错误" in result
