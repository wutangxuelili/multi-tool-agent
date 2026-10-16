"""运维脚本的测试：初始化数据库、兼容入口、checkpoint 清理。

这些脚本平时靠人手动跑，最容易"上线即腐化"，所以也纳入回归：
- `scripts/init_db.py` 能不能在任意 cwd、指定路径下建库；
- `scripts/inint_db.py` 兼容入口是否转发且给出弃用提示；
- `scripts/cleanup_checkpoints.py` 是否真的删掉过期快照、保留新快照。
"""

import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts import cleanup_checkpoints

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_script(script: str, env: dict, cwd: Path) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **env}
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / script)],
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,  # 由调用方断言 returncode（有的用例就是要看失败）
    )


def test_init_db_creates_database_at_env_path(tmp_path):
    db_path = tmp_path / "nested" / "company.db"
    result = _run_script("init_db.py", {"COMPANY_DB_PATH": str(db_path)}, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert db_path.exists(), "初始化脚本应按 COMPANY_DB_PATH 建库，而不是写死相对路径"

    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0] == 7
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
    assert {"employees", "deleted_employees"} <= tables


def test_init_db_is_cwd_independent(tmp_path):
    """旧的相对路径实现换目录就写错地方；现在必须与 cwd 无关。"""
    db_path = tmp_path / "company.db"
    other_cwd = tmp_path / "somewhere-else"
    other_cwd.mkdir()

    result = _run_script("init_db.py", {"COMPANY_DB_PATH": str(db_path)}, cwd=other_cwd)

    assert result.returncode == 0, result.stderr
    assert db_path.exists()
    assert not (other_cwd / "data").exists()


def test_inint_db_is_a_deprecated_shim(tmp_path):
    db_path = tmp_path / "company.db"
    result = _run_script("inint_db.py", {"COMPANY_DB_PATH": str(db_path)}, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert "deprecated" in result.stderr
    assert db_path.exists()


# ---------- checkpoint 清理 ----------


@pytest.fixture
def checkpoints_db(tmp_path, monkeypatch):
    """造一个只有 checkpoints/writes 两表的最小库，并让脚本指向它。"""
    db_path = tmp_path / "checkpoints.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE checkpoints (
            thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, thread_ts TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE writes (
            thread_id TEXT, checkpoint_ns TEXT, checkpoint_id TEXT, task_id TEXT
        )
        """
    )
    old_ts = (datetime.now() - timedelta(days=30)).isoformat()
    new_ts = datetime.now().isoformat()
    conn.execute("INSERT INTO checkpoints VALUES ('old', '', 'c1', ?)", (old_ts,))
    conn.execute("INSERT INTO checkpoints VALUES ('new', '', 'c2', ?)", (new_ts,))
    conn.execute("INSERT INTO writes VALUES ('old', '', 'c1', 't1')")
    conn.execute("INSERT INTO writes VALUES ('new', '', 'c2', 't2')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(cleanup_checkpoints, "CHECKPOINTS_DB", db_path)
    return db_path


def test_cleanup_checkpoints_removes_only_expired(checkpoints_db):
    deleted = cleanup_checkpoints.cleanup(days=7)
    assert deleted == 1

    conn = sqlite3.connect(checkpoints_db)
    try:
        remaining = [row[0] for row in conn.execute("SELECT thread_id FROM checkpoints")]
        left_writes = [row[0] for row in conn.execute("SELECT thread_id FROM writes")]
    finally:
        conn.close()

    assert remaining == ["new"]
    assert left_writes == ["new"]


def test_cleanup_checkpoints_dry_run_keeps_everything(checkpoints_db):
    assert cleanup_checkpoints.cleanup(days=7, dry_run=True) == 0

    conn = sqlite3.connect(checkpoints_db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0] == 2
    finally:
        conn.close()


def test_cleanup_checkpoints_without_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cleanup_checkpoints, "CHECKPOINTS_DB", tmp_path / "none.db")
    assert cleanup_checkpoints.cleanup(days=7) == 0
