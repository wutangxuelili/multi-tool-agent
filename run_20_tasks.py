"""20 任务测试：评估 Agent 完成率。

运行方式：
    python test_20_tasks.py                # 按规格关键词判定（主判定）
    python test_20_tasks.py --no-restore   # 跳过数据库还原

前置条件：
    1. 内部 API 服务运行中（端口 8001）  ← 唯一真正需要的服务
    2. 数据库已初始化（data/company.db）+ 纯净备份（data/company_backup.db）
    3. documents/test.txt 存在（MCP 读文件用）

注意：本项目代码中不包含任何 Qdrant / Redis 依赖（已全库检索确认），
      原始任务书里的 Qdrant / Redis 前置条件对本仓库不适用。

输出：
    - 每个任务的执行结果（含真实工具调用轨迹）
    - 完成率统计（规格判定 + 语义放宽判定，两套都给）
    - 失败任务的详细日志
"""

import argparse
import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# 从项目根目录运行，保证 tools/database.py 里的相对路径生效
PROJECT_ROOT = Path(__file__).resolve().parent
if Path.cwd() != PROJECT_ROOT:
    import os

    os.chdir(PROJECT_ROOT)

from main import CONFIRM_PREFIX, resume_agent, run_agent  # noqa: E402
from utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)

INTERNAL_API_BASE = "http://127.0.0.1:8001"
DB_PATH = PROJECT_ROOT / "data" / "company.db"
DB_BACKUP = PROJECT_ROOT / "data" / "company_backup.db"

# 本次运行的唯一前缀，避免历史 checkpoint 污染（checkpoints.db 里已有旧的 test-* 线程）
RUN_ID = datetime.now().strftime("%H%M%S")
THREAD_PREFIX = f"test-{RUN_ID}"

# ---------- 任务列表 ----------
# (编号, 类别, 任务描述, 预期关键词列表, 是否需要确认)
#
# alt_groups：语义等价的"任一即可"关键词组，用于第二套（放宽）判定。
#   规格判定要求"所有"N 个关键词都出现（≥80% 命中），这在实际中文回答里
#   等于强制模型同时说出所有同义词（例如必须同时出现"错误"+"除零"+"zero"）。
#   放宽判定允许每组命中任意一个同义表达，作为对照参考，不覆盖主判定。
TASKS = [
    (1, "单工具", "北京今天天气怎么样？", ["北京", "℃"], False, None),
    (2, "单工具", "(25 + 17) * 3 等于多少？", ["126"], False, None),
    (3, "单工具", "搜一下 Python asyncio 的教程", ["asyncio"], False, None),
    (4, "单工具", "公司技术部有哪些员工？", ["张三", "李四", "周八"], False, None),
    (5, "单工具", "公司最近有什么公告？", ["公告", "年会", "培训"], False, None),
    (6, "单工具", "读取 documents/test.txt", ["Hello from MCP!"], False, None),
    (7, "多工具", "北京天气怎么样？如果下雨就搜一下雨伞推荐", ["北京"], False, None),
    (8, "多工具", "技术部有多少人？平均薪资是多少？", ["3", "29333"], False, None),
    (
        9,
        "多工具",
        "搜一下 FastAPI 是什么，然后告诉我它和 Flask 的区别",
        ["FastAPI"],
        False,
        None,
    ),
    (10, "多工具", "公司有哪些部门？每个部门多少人？", ["技术部", "市场部"], False, None),
    (11, "多工具", "公司最近有什么培训相关公告？", ["培训"], False, None),
    (12, "敏感操作", "帮我删掉 ID 为 7 的员工", [CONFIRM_PREFIX], True, None),
    (13, "敏感操作", "(确认删除)", ["已删除"], True, None),
    (14, "敏感操作", "(拒绝删除)", ["取消"], True, None),
    (
        15,
        "边界",
        "查一下火星的天气",
        ["无法", "不支持", "火星"],
        False,
        [["无法", "不支持", "不能", "查询不到"], ["火星"]],
    ),
    (
        16,
        "边界",
        "帮我算 10/0",
        ["错误", "除零", "zero"],
        False,
        [["错误", "失败", "不能"], ["除零", "除以零", "除以 0", "division by zero", "zero"]],
    ),
    (17, "边界", "读取 documents/not_exist.txt", ["不存在", "错误"], False, None),
    (
        18,
        "边界",
        "今天股票行情怎么样？",
        ["无法", "不支持"],
        False,
        [["无法", "不支持", "不能", "没有"]],
    ),
    (19, "多步推理", "北京和上海哪个城市更热？", ["北京", "上海"], False, None),
    (20, "综合", "公司技术部平均薪资比市场部高多少？", ["技术部", "市场部"], False, None),
]


# ---------- 工具调用录制 ----------
# 原任务书只按关键词判定，无法区分"工具没被调用"和"回答了但没说对"。
# 这里包一层 TOOL_MAP，把真实调用的工具名记下来，供失败分析使用。
# 注意：只做记录，不改变任何 Agent 行为。

_TOOL_TRACE: list = []


class _ToolRecorder:
    """包装 LangChain 工具，记录调用轨迹后原样转发。"""

    def __init__(self, name, tool, sink):
        self.name = name
        self._tool = tool
        self._sink = sink

    def invoke(self, args, *a, **k):
        self._sink.append({"tool": self.name, "args": args})
        return self._tool.invoke(args, *a, **k)

    def __getattr__(self, item):
        return getattr(self._tool, item)


def install_tool_recorder() -> None:
    import agent.nodes as nodes_module

    nodes_module.TOOL_MAP = {
        name: _ToolRecorder(name, tool, _TOOL_TRACE)
        for name, tool in nodes_module.TOOL_MAP.items()
    }
    logger.info(f"已安装工具调用记录器，共 {len(nodes_module.TOOL_MAP)} 个工具")


# ---------- 数据库辅助 ----------


def restore_db() -> None:
    """用纯净备份还原数据库，保证测试可重复。"""
    if not DB_BACKUP.exists():
        raise FileNotFoundError(f"缺少数据库备份：{DB_BACKUP}")
    shutil.copyfile(DB_BACKUP, DB_PATH)


def employee_exists(employee_id: int) -> bool:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        row = conn.execute(
            "SELECT 1 FROM employees WHERE id = ?", (employee_id,)
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ---------- 判定 ----------


def judge(answer: str, keywords: list, alt_groups: list | None) -> dict:
    """返回规格判定与放宽判定的结果。"""
    answer_str = str(answer)

    matched = [kw for kw in keywords if kw in answer_str]
    rate = len(matched) / len(keywords) if keywords else 0.0

    if rate >= 0.8:
        spec_status = "✅"
    elif rate >= 0.5:
        spec_status = "⚠️"
    else:
        spec_status = "❌"

    if alt_groups:
        hit_groups = [g for g in alt_groups if any(kw in answer_str for kw in g)]
        alt_rate = len(hit_groups) / len(alt_groups)
        if alt_rate >= 0.8:
            alt_status = "✅"
        elif alt_rate >= 0.5:
            alt_status = "⚠️"
        else:
            alt_status = "❌"
    else:
        alt_rate = rate
        alt_status = spec_status
        hit_groups = matched

    return {
        "status": spec_status,
        "matched": matched,
        "match_rate": rate,
        "alt_status": alt_status,
        "alt_matched": hit_groups,
        "alt_match_rate": alt_rate,
    }


# ---------- 单任务执行 ----------


def _drive(task: str, thread_id: str, decision: str, need_confirm: bool) -> tuple:
    """跑一次 Agent 交互，必要时自动完成确认循环。

    返回 (最终回答, 是否发生过中断, 中断次数)。
    """
    answer = run_agent(task, thread_id=thread_id)
    interrupts = 0

    # 敏感操作：可能连续多次中断，用同一个 decision 回复（最多 3 次）
    while str(answer).startswith(CONFIRM_PREFIX) and need_confirm and interrupts < 3:
        interrupts += 1
        print(f"  → 触发确认，自动回复: {decision}")
        answer = resume_agent(decision, thread_id=thread_id)

    return answer, interrupts > 0, interrupts


def run_single_task(
    task_id: int,
    category: str,
    task: str,
    expected_keywords: list,
    need_confirm: bool,
    alt_groups: list | None = None,
    shared_thread: str | None = None,
) -> dict:
    """执行单个任务，返回结果字典。"""
    print(f"\n{'=' * 60}")
    print(f"任务 {task_id} [{category}]: {task}")
    print("=" * 60)

    start = time.time()
    result = {
        "id": task_id,
        "category": category,
        "task": task,
        "status": None,
        "answer": None,
        "matched": [],
        "elapsed": 0,
        "error": None,
        "tools": [],
        "interrupted": False,
    }

    thread_id = shared_thread or f"{THREAD_PREFIX}-{task_id}"
    _TOOL_TRACE.clear()

    # 敏感操作三个阶段共用一条流程，decision 由任务编号决定
    decision = "yes" if task_id == 13 else "no"

    try:
        answer, interrupted, n_interrupts = _drive(
            task, thread_id, decision, need_confirm
        )
        result["interrupted"] = interrupted
        result["interrupt_count"] = n_interrupts

        verdict = judge(str(answer), expected_keywords, alt_groups)
        result.update(verdict)
        result["answer"] = str(answer)

        # 不该触发确认却触发了 → 判失败
        if interrupted and not need_confirm:
            result["status"] = "❌"
            result["error"] = "意外触发确认"

        logger.info(f"任务 {task_id} 工具轨迹: {[t['tool'] for t in _TOOL_TRACE]}")

    except Exception as e:  # noqa: BLE001
        result["status"] = "❌"
        result["error"] = f"{type(e).__name__}: {e}"
        logger.exception(f"任务 {task_id} 异常")

    result["tools"] = [t["tool"] for t in _TOOL_TRACE]
    result["tool_calls"] = list(_TOOL_TRACE)
    result["elapsed"] = time.time() - start

    print(f"  → 状态: {result['status']}, 耗时: {result['elapsed']:.2f}s")
    print(f"  → 工具: {result['tools']}")
    if result["error"]:
        print(f"  → 错误: {result['error']}")
    else:
        print(f"  → 回答: {(result['answer'] or '')[:200]}")

    return result


# ---------- 敏感操作三阶段（12/13/14）----------
# 规格书的风险表说"任务 12/13/14 共享同一个 thread_id 会混乱，用 test-12/13/14 区分"。
# 但 resume_agent() 必须在**产生中断的那条线程**上恢复，换线程就找不到中断状态，
# 所以按规格书字面实现时，13/14 必然失败（它们只是往新线程发"(确认删除)"，
# 根本不会触发中断）。这里按中断语义正确实现：
#   12：新线程发起删除 → 触发中断，此时不做决定
#   13：在同一条线程上回复 yes → 真删；校验数据库里 ID 7 确实消失
#   14：还原数据库后新线程发起删除 → 回复 no → 取消；校验 ID 7 仍在
# 这样才真正测到规格书判定标准里写的"员工被删除"/"员工未删除"。


def run_sensitive_tasks() -> list:
    results = []

    # --- 任务 12：触发确认 ---
    thread12 = f"{THREAD_PREFIX}-12"
    _TOOL_TRACE.clear()
    start = time.time()
    print(f"\n{'=' * 60}")
    print("任务 12 [敏感操作]: 帮我删掉 ID 为 7 的员工（应触发确认）")
    print("=" * 60)
    answer = run_agent("帮我删掉 ID 为 7 的员工", thread_id=thread12)
    elapsed = time.time() - start
    triggered = str(answer).startswith(CONFIRM_PREFIX)
    still_there = employee_exists(7)
    status = "✅" if (triggered and still_there) else ("⚠️" if triggered else "❌")
    print(f"  → 触发中断: {triggered}, 员工仍在: {still_there}")
    print(f"  → 回答: {str(answer)[:200]}")
    results.append(
        {
            "id": 12,
            "category": "敏感操作",
            "task": "帮我删掉 ID 为 7 的员工",
            "status": status,
            "matched": [CONFIRM_PREFIX] if triggered else [],
            "match_rate": 1.0 if triggered else 0.0,
            "alt_status": status,
            "alt_matched": [],
            "alt_match_rate": 0.0,
            "answer": str(answer),
            "elapsed": elapsed,
            "error": None if triggered else "未触发 NEED_CONFIRM 中断",
            "tools": [t["tool"] for t in _TOOL_TRACE],
            "tool_calls": list(_TOOL_TRACE),
            "interrupted": triggered,
            "db_check": f"employee 7 exists={still_there} (期望 True)",
        }
    )

    # --- 任务 13：确认 yes → 应真删 ---
    _TOOL_TRACE.clear()
    start = time.time()
    print(f"\n{'=' * 60}")
    print("任务 13 [敏感操作]: 同一线程回复 yes（应执行删除）")
    print("=" * 60)
    answer = resume_agent("yes", thread_id=thread12)
    # 可能再次中断
    extra = 0
    while str(answer).startswith(CONFIRM_PREFIX) and extra < 2:
        extra += 1
        answer = resume_agent("yes", thread_id=thread12)
    elapsed = time.time() - start
    deleted = not employee_exists(7)
    text = str(answer)
    kw_hit = "已删除" in text
    if deleted and kw_hit:
        status = "✅"
    elif deleted:
        status = "⚠️"
    else:
        status = "❌"
    print(f"  → 员工已删除: {deleted}, 回答含'已删除': {kw_hit}")
    print(f"  → 回答: {text[:200]}")
    results.append(
        {
            "id": 13,
            "category": "敏感操作",
            "task": "(确认删除 yes)",
            "status": status,
            "matched": ["已删除"] if kw_hit else [],
            "match_rate": 1.0 if kw_hit else 0.0,
            "alt_status": status,
            "alt_matched": [],
            "alt_match_rate": 0.0,
            "answer": text,
            "elapsed": elapsed,
            "error": None if deleted else "确认后员工仍未被删除",
            "tools": [t["tool"] for t in _TOOL_TRACE],
            "tool_calls": list(_TOOL_TRACE),
            "interrupted": False,
            "db_check": f"employee 7 exists={not deleted} (期望 False)",
        }
    )

    # --- 任务 14：还原后 no → 应取消 ---
    restore_db()
    thread14 = f"{THREAD_PREFIX}-14"
    _TOOL_TRACE.clear()
    start = time.time()
    print(f"\n{'=' * 60}")
    print("任务 14 [敏感操作]: 重新发起删除后回复 no（应取消）")
    print("=" * 60)
    first = run_agent("帮我删掉 ID 为 7 的员工", thread_id=thread14)
    triggered14 = str(first).startswith(CONFIRM_PREFIX)
    if triggered14:
        answer = resume_agent("no", thread_id=thread14)
    else:
        answer = first
    extra = 0
    while str(answer).startswith(CONFIRM_PREFIX) and extra < 2:
        extra += 1
        answer = resume_agent("no", thread_id=thread14)
    elapsed = time.time() - start
    survived = employee_exists(7)
    text = str(answer)
    kw_hit = "取消" in text
    if survived and kw_hit:
        status = "✅"
    elif survived:
        status = "⚠️"
    else:
        status = "❌"
    print(f"  → 员工仍在: {survived}, 回答含'取消': {kw_hit}")
    print(f"  → 回答: {text[:200]}")
    results.append(
        {
            "id": 14,
            "category": "敏感操作",
            "task": "(拒绝删除 no)",
            "status": status,
            "matched": ["取消"] if kw_hit else [],
            "match_rate": 1.0 if kw_hit else 0.0,
            "alt_status": status,
            "alt_matched": [],
            "alt_match_rate": 0.0,
            "answer": text,
            "elapsed": elapsed,
            "error": None if (survived and kw_hit) else "拒绝后状态不符合预期",
            "tools": [t["tool"] for t in _TOOL_TRACE],
            "tool_calls": list(_TOOL_TRACE),
            "interrupted": triggered14,
            "db_check": f"employee 7 exists={survived} (期望 True)",
        }
    )

    return results


# ---------- 前置检查 ----------


def check_prerequisites() -> list:
    """返回 (是否通过, 说明) 列表。"""
    checks = []

    # 内部 API
    try:
        r = requests.get(f"{INTERNAL_API_BASE}/health", timeout=5)
        ok = r.status_code == 200 and r.json().get("status") == "ok"
        checks.append((ok, f"内部 API {INTERNAL_API_BASE}/health → {r.text.strip()}"))
    except Exception as e:  # noqa: BLE001
        checks.append((False, f"内部 API 不可用: {type(e).__name__}: {e}"))

    # 数据库
    checks.append((DB_PATH.exists(), f"数据库 {DB_PATH.name} 存在={DB_PATH.exists()}"))
    checks.append(
        (DB_BACKUP.exists(), f"纯净备份 {DB_BACKUP.name} 存在={DB_BACKUP.exists()}")
    )

    # MCP 依赖文件
    test_txt = PROJECT_ROOT / "documents" / "test.txt"
    checks.append((test_txt.exists(), f"MCP 测试文件 {test_txt.name} 存在={test_txt.exists()}"))

    return checks


# ---------- 主函数 ----------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-restore", action="store_true", help="跳过运行前的数据库还原"
    )
    parser.add_argument(
        "--only",
        default=None,
        help="只跑指定任务编号，逗号分隔，例如 --only 1,2,6（调试用）",
    )
    args = parser.parse_args()

    only = None
    if args.only:
        only = {int(x) for x in args.only.split(",") if x.strip()}

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    logger.info(f"开始 20 任务测试，共 {len(TASKS)} 个任务，RUN_ID={RUN_ID}")

    print("=" * 60)
    print("前置检查")
    print("=" * 60)
    prereq_ok = True
    for ok, msg in check_prerequisites():
        print(f"  [{'OK' if ok else 'FAIL'}] {msg}")
        prereq_ok = prereq_ok and ok
    if not prereq_ok:
        print("\n前置条件不满足，终止测试。")
        return 2

    if not args.no_restore:
        restore_db()
        print("\n  [OK] 已从备份还原 data/company.db（保证可重复）")

    install_tool_recorder()

    results = []
    if only is None or only & {12, 13, 14}:
        print("\n" + "#" * 60)
        print("# 敏感操作三阶段（任务 12 / 13 / 14）")
        print("#" * 60)
        sensitive = run_sensitive_tasks()
        if only is not None:
            sensitive = [r for r in sensitive if r["id"] in only]
        results.extend(sensitive)

    for tid, cat, task, kws, need_confirm, alt in TASKS:
        if tid in (12, 13, 14):
            continue
        if only is not None and tid not in only:
            continue
        r = run_single_task(tid, cat, task, kws, need_confirm, alt)
        results.append(r)

    # 保持任务编号顺序
    results.sort(key=lambda r: r["id"])

    # ---------- 统计 ----------
    total = len(results)
    success = sum(1 for r in results if r["status"] == "✅")
    partial = sum(1 for r in results if r["status"] == "⚠️")
    fail = sum(1 for r in results if r["status"] == "❌")
    completion_rate = (success + 0.5 * partial) / total

    alt_success = sum(1 for r in results if r.get("alt_status") == "✅")
    alt_partial = sum(1 for r in results if r.get("alt_status") == "⚠️")
    alt_fail = sum(1 for r in results if r.get("alt_status") == "❌")
    alt_rate = (alt_success + 0.5 * alt_partial) / total

    categories = {}
    for r in results:
        cat = r["category"]
        categories.setdefault(cat, {"✅": 0, "⚠️": 0, "❌": 0, "total": 0})
        categories[cat][r["status"]] += 1
        categories[cat]["total"] += 1

    total_elapsed = sum(r["elapsed"] for r in results)

    # ---------- 输出报告 ----------
    print("\n" + "=" * 60)
    print("测试报告")
    print("=" * 60)
    print(f"总任务数: {total}")
    print(f"✅ 成功: {success}")
    print(f"⚠️ 部分成功: {partial}")
    print(f"❌ 失败: {fail}")
    print(f"完成率: {completion_rate:.1%}   (目标 ≥ 70%)")
    print(f"[放宽关键词判定] 完成率: {alt_rate:.1%} ({alt_success}/{alt_partial}/{alt_fail})")
    print(f"总耗时: {total_elapsed:.1f}s")
    print(f"平均耗时: {total_elapsed / total:.1f}s")

    print("\n按类别统计:")
    for cat, stats in categories.items():
        rate = (stats["✅"] + 0.5 * stats["⚠️"]) / stats["total"]
        print(f"  {cat}: {rate:.0%} ({stats['✅']}/{stats['total']})")

    print("\n失败任务:")
    for r in results:
        if r["status"] == "❌":
            print(f"  #{r['id']} {r['task'][:40]}")
            print(f"    工具: {r.get('tools')}")
            if r["error"]:
                print(f"    错误: {r['error'][:100]}")
            print(f"    回答: {(r.get('answer') or '')[:150]}")

    print("\n部分成功任务:")
    for r in results:
        if r["status"] == "⚠️":
            print(f"  #{r['id']} {r['task'][:40]}")
            print(f"    工具: {r.get('tools')}")
            print(f"    匹配: {r.get('matched', [])}")
            print(f"    回答: {(r.get('answer') or '')[:150]}")

    # ---------- 保存文件 ----------
    output_file = Path("test_20_tasks_result.md")
    with output_file.open("w", encoding="utf-8") as f:
        f.write("# 20 任务测试报告\n\n")
        f.write(f"- 运行时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        f.write(f"- 线程前缀: `{THREAD_PREFIX}`\n")
        f.write(f"- 总任务数: {total}\n")
        f.write(f"- **完成率: {completion_rate:.1%}**（目标 ≥ 70%）\n")
        f.write(f"- 成功: {success} / 部分成功: {partial} / 失败: {fail}\n")
        f.write(
            f"- 放宽关键词判定完成率: {alt_rate:.1%}"
            f"（{alt_success} / {alt_partial} / {alt_fail}）\n"
        )
        f.write(f"- 总耗时: {total_elapsed:.1f}s，平均 {total_elapsed / total:.1f}s\n\n")

        f.write("## 按类别统计\n\n")
        f.write("| 类别 | 完成率 | ✅ | ⚠️ | ❌ | 合计 |\n")
        f.write("|------|--------|----|----|----|------|\n")
        for cat, stats in categories.items():
            rate = (stats["✅"] + 0.5 * stats["⚠️"]) / stats["total"]
            f.write(
                f"| {cat} | {rate:.0%} | {stats['✅']} | {stats['⚠️']}"
                f" | {stats['❌']} | {stats['total']} |\n"
            )

        f.write("\n## 详细结果\n\n")
        f.write("| # | 类别 | 任务 | 状态 | 实际调用工具 | 耗时 | 回答摘要 |\n")
        f.write("|---|------|------|------|--------------|------|----------|\n")
        for r in results:
            answer_preview = (
                (r["answer"] or r["error"] or "")
                .replace("\n", " ")
                .replace("|", "\\|")[:70]
            )
            tools = ", ".join(r.get("tools") or []) or "—"
            f.write(
                f"| {r['id']} | {r['category']} | {r['task'][:26]} | {r['status']}"
                f" | {tools} | {r['elapsed']:.1f}s | {answer_preview} |\n"
            )

        f.write("\n## 失败与部分成功详情\n\n")
        for r in results:
            if r["status"] == "✅":
                continue
            f.write(f"### #{r['id']} {r['task']}　{r['status']}\n\n")
            f.write(f"- 类别: {r['category']}\n")
            f.write(f"- 期望关键词: {TASKS[r['id'] - 1][3]}\n")
            f.write(f"- 命中: {r.get('matched')}\n")
            f.write(f"- 实际调用工具: {r.get('tools')}\n")
            if r.get("db_check"):
                f.write(f"- 数据库校验: {r['db_check']}\n")
            if r.get("interrupted") is not None:
                f.write(f"- 是否中断: {r.get('interrupted')}\n")
            if r.get("error"):
                f.write(f"- 错误: {r['error']}\n")
            f.write(f"\n**完整回答**：\n\n```\n{r.get('answer') or '(无)'}\n```\n\n")

        f.write("\n## 原始结果 JSON\n\n```json\n")
        f.write(json.dumps(results, ensure_ascii=False, indent=2))
        f.write("\n```\n")

    print(f"\n报告已保存至: {output_file}")
    return 0 if completion_rate >= 0.7 else 1


if __name__ == "__main__":
    sys.exit(main())
