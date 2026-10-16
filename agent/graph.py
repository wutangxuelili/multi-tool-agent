"""LangGraph 主图的构建与编译。

图结构：
    [info] ──有 pending_tool──→ [confirm] ──→ [info]
       │
       ├──需要计算──→ [calc] ──→ [writer]
       │
       └──其他情况──→ [writer] ──→ END
"""

import atexit
import re
import sqlite3
from functools import lru_cache

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from agent.nodes import calc_node, confirm_node, info_node, writer_node
from agent.state import State
from utils.logger import get_logger
from utils.paths import CHECKPOINTS_DB

logger = get_logger(__name__)

# AI 自己说"需要计算"时的触发词（历史行为，保留）
CALC_KEYWORDS = ["需要计算", "计算一下", "算一下", "帮我算", "需要算", "做个计算"]

# 用户提问里的算术意图。旧实现只看 AI 的输出，模型一句"我直接心算"就绕过了整个计算器；
# 现在**同时看用户问的是什么**，因为"要不要算"这件事用户比模型更可靠。
CALC_INTENT_KEYWORDS = [
    "计算",
    "算一下",
    "帮我算",
    "换算",
    "求和",
    "总和",
    "合计",
    "平均",
    "均值",
    "百分比",
    "增长率",
    "占比",
    "总共",
    "一共",
    "多少倍",
    "等于多少",
    "多少钱",
]
# 数字 + 运算符（含中文/全角符号）："(25 + 17) * 3"、"10/0"、"3×4"、"15%"
CALC_INTENT_PATTERN = re.compile(r"\d\s*[+\-*/×÷^%＝=]|[+\-*/×÷]\s*\d")


def looks_like_arithmetic(text: str) -> bool:
    """判断一段自然语言里是否含明确的算术意图。"""
    if not text:
        return False
    if CALC_INTENT_PATTERN.search(text):
        return True
    return any(keyword in text for keyword in CALC_INTENT_KEYWORDS)


def route_after_info(state: State) -> str:
    """info 节点执行后的路由决策。

    优先级：
    1. 有 pending_tool → confirm（敏感操作优先）
    2. 用户提问或 AI 输出里有算术意图 → calc
    3. 否则 → writer
    """
    # 1. 敏感操作优先
    if state.get("pending_tool"):
        return "confirm"

    # 2. 用户提问里的算术意图（更可靠），或 AI 自己声明"需要计算"
    messages = state.get("messages") or []
    user_text = ""
    for message in reversed(messages):
        if getattr(message, "type", "") == "human":
            user_text = str(getattr(message, "content", "") or "")
            break
    if looks_like_arithmetic(user_text):
        logger.debug("[route_after_info] 命中用户提问的算术意图 → calc")
        return "calc"

    last_message = messages[-1]
    content = str(getattr(last_message, "content", "") or "")
    if any(kw in content for kw in CALC_KEYWORDS):
        return "calc"

    # 3. 默认走 writer
    return "writer"


@lru_cache(maxsize=1)
def default_checkpointer() -> SqliteSaver:
    """进程内共享的 SqliteSaver（跨进程恢复靠同一个 checkpoints.db 文件）。"""
    conn = sqlite3.connect(str(CHECKPOINTS_DB), check_same_thread=False)
    return SqliteSaver(conn)


def close_checkpointer() -> None:
    """关闭共享的 checkpoint 连接（进程退出或测试收尾时调用）。

    `checkpoints.db` 只增不减，长期运行请配合 scripts/cleanup_checkpoints.py 清理。
    """
    if default_checkpointer.cache_info().currsize:
        saver = default_checkpointer()
        conn = getattr(saver, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error as e:  # pragma: no cover - 关闭失败不应影响退出
                logger.warning(f"[checkpointer] 关闭连接失败: {e}")
        default_checkpointer.cache_clear()


atexit.register(close_checkpointer)


def build_graph(checkpointer=None):
    """构建并编译主图。

    :param checkpointer: 自定义 checkpointer；测试用 InMemorySaver 注入，
        不传则使用默认的 SqliteSaver。
    """
    graph = StateGraph(State)

    graph.add_node("info", info_node)
    graph.add_node("calc", calc_node)
    graph.add_node("writer", writer_node)
    graph.add_node("confirm", confirm_node)

    graph.set_entry_point("info")

    graph.add_conditional_edges(
        "info",
        route_after_info,
        {
            "confirm": "confirm",
            "calc": "calc",
            "writer": "writer",
        },
    )

    graph.add_edge("confirm", "info")
    graph.add_edge("calc", "writer")
    graph.add_edge("writer", END)

    return graph.compile(checkpointer=checkpointer or default_checkpointer())


app = build_graph()
