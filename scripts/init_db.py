"""初始化公司员工库（重建表并写入示例数据）。

用法（在项目根目录，或在任意目录直接给脚本路径）：

    python scripts/init_db.py

说明：本文件是 `scripts/inint_db.py` 的**正名版**（旧名拼写有误）。
旧文件保留为兼容入口，会在下个版本移除。
"""

import sqlite3
import sys
from pathlib import Path

# 允许直接 `python scripts/init_db.py` 运行（此时 sys.path[0] 是 scripts/）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.paths import COMPANY_DB  # noqa: E402  （必须在 sys.path 调整之后导入）

# 与 tools/database_admin.py 的归档表保持一致：删除是"先归档再删除"
ARCHIVE_TABLE = "deleted_employees"

SCHEMA = """
    CREATE TABLE employees (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        department TEXT NOT NULL,
        salary INTEGER NOT NULL,
        hire_date TEXT NOT NULL
    )
"""

ARCHIVE_SCHEMA = f"""
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

EMPLOYEES = [
    ("张三", "技术部", 25000, "2021-03-15"),
    ("李四", "技术部", 28000, "2020-07-01"),
    ("王五", "市场部", 18000, "2022-01-10"),
    ("赵六", "市场部", 22000, "2019-11-20"),
    ("孙七", "人事部", 15000, "2023-05-08"),
    ("周八", "技术部", 35000, "2018-09-01"),
    ("吴九", "财务部", 20000, "2021-12-15"),
]


def main() -> None:
    COMPANY_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(COMPANY_DB)
    try:
        with conn:
            conn.execute("DROP TABLE IF EXISTS employees")
            conn.execute(SCHEMA)
            conn.execute(ARCHIVE_SCHEMA)
            conn.executemany(
                "INSERT INTO employees (name, department, salary, hire_date)"
                " VALUES (?, ?, ?, ?)",
                EMPLOYEES,
            )
    finally:
        conn.close()
    print(f"数据库创建完成：{COMPANY_DB}")


if __name__ == "__main__":
    main()
