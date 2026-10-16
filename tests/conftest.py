"""tests/ 公共 fixture。

原则：**测试不得依赖开发库、网络和 API Key**。
- 数据库：每个用例在 tmp_path 里自建临时库，并把工具指向它；
- LLM：图级测试通过 monkeypatch 注入脚本化的假 LLM（见 test_agent_graph.py）。
"""

import sqlite3

import pytest

from tools import db_config

# 临时库里的固定数据（与 scripts/init_db.py 的结构一致，但只有 4 行，
# 数据量小、断言更直观）
EMPLOYEES = [
    (1, "张三", "技术部", 25000, "2021-03-15"),
    (2, "李四", "技术部", 28000, "2020-07-01"),
    (3, "王五", "市场部", 18000, "2022-01-10"),
    (4, "周八", "技术部", 35000, "2018-09-01"),
]


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """建一个只属于本次测试的数据库，并让所有 DB 工具指向它。"""
    db_file = tmp_path / "company.db"
    conn = sqlite3.connect(db_file)
    conn.execute(
        """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            salary INTEGER NOT NULL,
            hire_date TEXT NOT NULL
        )
        """
    )
    conn.executemany(
        "INSERT INTO employees (id, name, department, salary, hire_date)"
        " VALUES (?, ?, ?, ?, ?)",
        EMPLOYEES,
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(db_config, "DB_PATH", db_file)
    return db_file


@pytest.fixture
def employee_count(temp_db):
    """返回一个可调用对象：读出临时库当前的员工行数。"""

    def _count() -> int:
        conn = sqlite3.connect(temp_db)
        try:
            return conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        finally:
            conn.close()

    return _count
