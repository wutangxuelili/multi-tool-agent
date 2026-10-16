"""敏感操作的审计记录（append-only JSON Lines）。

为什么需要：`delete_employee` 这类操作一旦放行就无法撤销，"谁在什么时候批准了什么"
必须留痕，且不能只依赖 INFO 日志（日志会被轮转、格式会变、混在对话日志里）。

用法：
    from utils.audit import record_sensitive_op
    record_sensitive_op(tool="delete_employee", args={"employee_id": 7},
                        decision="approved", answer="yes", result="已删除…",
                        thread_id="t1")

落盘位置默认 `logs/sensitive_ops.jsonl`，可用环境变量 `SENSITIVE_AUDIT_LOG` 覆盖。
审计写入失败**不会**影响主流程（只记一条警告），避免为了留痕把业务搞挂。
"""

import json
import os
import threading
from datetime import datetime
from pathlib import Path

from utils.logger import get_logger
from utils.paths import AUDIT_LOG as DEFAULT_AUDIT_PATH

logger = get_logger(__name__)

AUDIT_PATH = Path(os.getenv("SENSITIVE_AUDIT_LOG") or DEFAULT_AUDIT_PATH)

_write_lock = threading.Lock()


def record_sensitive_op(
    *,
    tool: str,
    args: dict | None,
    decision: str,
    answer: str | None = None,
    result: str | None = None,
    thread_id: str | None = None,
    path: Path | str | None = None,
) -> dict | None:
    """追加一条敏感操作审计记录。

    :param decision: "approved" / "rejected"
    :return: 写入的记录；写入失败时返回 None
    """
    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "thread_id": thread_id,
        "tool": tool,
        "args": args,
        "decision": decision,
        "answer": answer,
        "result": result,
    }

    target = Path(path) if path is not None else AUDIT_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False)
        with _write_lock, target.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:  # 审计失败不应影响业务
        logger.warning(f"[audit] 审计记录写入失败：{type(e).__name__}: {e}")
        return None

    logger.info(f"[audit] {decision} {tool} args={args}")
    return record
