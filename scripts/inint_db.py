import os
import sqlite3

os.makedirs("data", exist_ok=True)

conn = sqlite3.connect("data/company.db")
cursor = conn.cursor()

cursor.execute("DROP TABLE IF EXISTS employees")
cursor.execute("""
    CREATE TABLE employees (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        department TEXT NOT NULL,
        salary INTEGER NOT NULL,
        hire_date TEXT NOT NULL
    )
""")

employees = [
    ("张三", "技术部", 25000, "2021-03-15"),
    ("李四", "技术部", 28000, "2020-07-01"),
    ("王五", "市场部", 18000, "2022-01-10"),
    ("赵六", "市场部", 22000, "2019-11-20"),
    ("孙七", "人事部", 15000, "2023-05-08"),
    ("周八", "技术部", 35000, "2018-09-01"),
    ("吴九", "财务部", 20000, "2021-12-15"),
]
cursor.executemany(
    "INSERT INTO employees (name, department, salary, hire_date) VALUES (?, ?, ?, ?)",
    employees,
)

conn.commit()
conn.close()
print("数据库创建完成：data/company.db")
