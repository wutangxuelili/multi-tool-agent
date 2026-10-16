"""数据库工具的单元测试。

这些用例**不碰开发库**：`temp_db` fixture（见 tests/conftest.py）会在 tmp_path
里建一个临时库，再把 `tools.db_config.DB_PATH` 指过去。因此
- 不需要预先跑 `scripts/init_db.py`；
- 用 Agent 删了员工也不会把测试搞红（旧实现断言开发库有 7 行，一删就挂）。
"""

import sqlite3

import pytest

from tools import db_config
from tools.database import query_database
from tools.database_admin import delete_employee
from utils.operator import operator_scope


def _parse_rows(result: str) -> list[list[str]]:
    """把 "col | col\\n---\\nrow..." 解析成二维列表（忽略空行后的提示信息）。"""
    body = result.split("\n\n", 1)[0]
    lines = [ln for ln in body.splitlines() if ln.strip()]
    return [ln.split(" | ") for ln in lines[2:]]


def test_count_employees(temp_db):
    rows = _parse_rows(query_database.invoke({"sql": "SELECT COUNT(*) AS n FROM employees"}))
    assert rows == [["4"]]


def test_query_by_department(temp_db):
    result = query_database.invoke(
        {"sql": "SELECT name FROM employees WHERE department = '技术部'"}
    )
    names = [row[0] for row in _parse_rows(result)]
    assert set(names) == {"张三", "李四", "周八"}


def test_non_select_is_rejected(temp_db):
    result = query_database.invoke({"sql": "DROP TABLE employees"})
    assert "只允许 SELECT" in result


def test_multiple_statements_are_rejected(temp_db):
    result = query_database.invoke({"sql": "SELECT 1; DROP TABLE employees"})
    assert "不允许多条" in result


def test_missing_database_gives_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setattr(db_config, "DB_PATH", tmp_path / "not_exist.db")
    assert "init_db.py" in query_database.invoke({"sql": "SELECT 1"})


@pytest.mark.parametrize("sql", ["DELETE FROM employees", "SELECT * FROM employees"])
def test_readonly_connection_is_actually_readonly(temp_db, sql, employee_count):
    """即使语句层校验被绕过，只读连接也写不进去。"""
    query_database.invoke({"sql": sql})
    assert employee_count() == 4


# ---------- 数据分级：敏感列默认脱敏（P2-8） ----------


def test_salary_is_masked_by_default(temp_db):
    result = query_database.invoke({"sql": "SELECT name, salary FROM employees WHERE id = 1"})
    assert "25000" not in result
    assert "***" in result
    assert "脱敏" in result


def test_salary_visible_only_when_authorized(temp_db, monkeypatch):
    monkeypatch.setenv("DB_SHOW_SALARY", "1")
    result = query_database.invoke({"sql": "SELECT name, salary FROM employees WHERE id = 1"})
    assert "25000" in result
    assert "***" not in result


def test_aggregate_over_salary_is_also_masked(temp_db):
    result = query_database.invoke(
        {"sql": "SELECT AVG(salary) AS avg_salary FROM employees"}
    )
    assert "***" in result
    assert "26500" not in result


def test_non_sensitive_columns_are_not_masked(temp_db):
    result = query_database.invoke({"sql": "SELECT name, department FROM employees"})
    assert "***" not in result


# ---------- 删除：先归档再删（P2-8） ----------


def test_delete_employee_archives_row_with_operator(temp_db, employee_count):
    with operator_scope("user-42"):
        assert "已删除" in delete_employee.invoke({"employee_id": 1})
    assert employee_count() == 3

    conn = sqlite3.connect(temp_db)
    try:
        row = conn.execute(
            "SELECT name, department, deleted_by, deleted_at FROM deleted_employees WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None, "被删除的行必须归档，才能追溯/回滚"
    assert row[0] == "张三"
    assert row[1] == "技术部"
    assert row[2] == "user-42"
    assert row[3]


def test_delete_without_operator_still_archives(temp_db, employee_count):
    assert "已删除" in delete_employee.invoke({"employee_id": 2})
    assert employee_count() == 3

    conn = sqlite3.connect(temp_db)
    try:
        row = conn.execute("SELECT deleted_by FROM deleted_employees WHERE id = 2").fetchone()
    finally:
        conn.close()
    assert row[0] is None


def test_delete_employee_unknown_id(temp_db, employee_count):
    assert "未找到" in delete_employee.invoke({"employee_id": 999})
    assert employee_count() == 4


def test_delete_employee_missing_database(tmp_path, monkeypatch):
    monkeypatch.setattr(db_config, "DB_PATH", tmp_path / "not_exist.db")
    result = delete_employee.invoke({"employee_id": 1})
    assert "删除失败" in result and "init_db.py" in result
