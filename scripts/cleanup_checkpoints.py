"""清理 LangGraph 的 checkpoint 快照（`checkpoints.db` 只增不减）。

用法：

    python scripts/cleanup_checkpoints.py                # 删除 7 天前的快照
    python scripts/cleanup_checkpoints.py --days 1
    python scripts/cleanup_checkpoints.py --vacuum       # 顺手回收磁盘空间
    python scripts/cleanup_checkpoints.py --dry-run      # 只看会删多少

说明：LangGraph 的 SqliteSaver 会在每一步写入快照，长时间运行后数据库会不断变大。
本脚本按 `checkpoints` 表的 `thread_ts`（时间戳）删除旧记录；没有该表的库会直接退出。
"""

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.paths import CHECKPOINTS_DB  # noqa: E402

# SqliteSaver 的表：checkpoints / writes（以及可选的 checkpoint_blobs / checkpoint_migrations）
TABLES = ("writes", "checkpoints")


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def cleanup(days: int, *, dry_run: bool = False, vacuum: bool = False) -> int:
    """删除 days 天前的快照，返回删除的 checkpoint 行数。"""
    if not CHECKPOINTS_DB.exists():
        print(f"没有找到 {CHECKPOINTS_DB}，无需清理。")
        return 0

    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = sqlite3.connect(CHECKPOINTS_DB)
    try:
        if not _has_table(conn, "checkpoints"):
            print("该数据库里没有 LangGraph 的 checkpoints 表，无需清理。")
            return 0

        expired = [
            row[0]
            for row in conn.execute(
                "SELECT thread_id FROM checkpoints WHERE thread_ts < ?", (cutoff,)
            ).fetchall()
        ]
        # 同一个 thread 可能有多个快照，按 (thread_id, checkpoint_ns, checkpoint_id) 精确删
        targets = conn.execute(
            "SELECT thread_id, checkpoint_ns, checkpoint_id FROM checkpoints"
            " WHERE thread_ts < ?",
            (cutoff,),
        ).fetchall()

        print(f"截止时间 {cutoff}：匹配到 {len(targets)} 个旧快照，涉及 {len(set(expired))} 个会话。")
        if dry_run or not targets:
            return 0

        with conn:
            for thread_id, ns, checkpoint_id in targets:
                for table in TABLES:
                    if _has_table(conn, table):
                        conn.execute(
                            f"DELETE FROM {table} WHERE thread_id = ?"
                            " AND checkpoint_ns = ? AND checkpoint_id = ?",
                            (thread_id, ns, checkpoint_id),
                        )
        if vacuum:
            conn.execute("VACUUM")
    finally:
        conn.close()

    print(f"已删除 {len(targets)} 个旧快照。")
    return len(targets)


def main() -> int:
    parser = argparse.ArgumentParser(description="清理旧的 LangGraph checkpoint 快照")
    parser.add_argument("--days", type=int, default=7, help="保留最近多少天（默认 7）")
    parser.add_argument("--dry-run", action="store_true", help="只统计不删除")
    parser.add_argument("--vacuum", action="store_true", help="清理后回收磁盘空间")
    args = parser.parse_args()

    cleanup(args.days, dry_run=args.dry_run, vacuum=args.vacuum)
    return 0


if __name__ == "__main__":
    sys.exit(main())
