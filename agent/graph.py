"""LangGraph 主图的构建与编译。

图结构：
    [info] ──有 pending_tool──→ [confirm] ──→ [info]
       │
       ├──需要计算──→ [calc] ──→ [writer]
       │
       └──其他情况──→ [writer] ──→ END
"""

import sqlite3

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from agent.nodes import calc_node, confirm_node, info_node, writer_node
from agent.state import State

# 判断是否需要进入计算阶段的关键词
CALC_KEYWORDS = ["需要计算", "计算一下", "算一下", "帮我算", "需要算", "做个计算"]


def route_after_info(state: State) -> str:
    """info 节点执行后的路由决策。

    优先级：
    1. 有 pending_tool → confirm
    2. 最后一条 AI 消息包含计算关键词 → calc
    3. 否则 → writer
    """
    # 1. 敏感操作优先
    if state.get("pending_tool"):
        return "confirm"

    # 2. 检查是否需要计算
    last_message = state["messages"][-1]
    content = getattr(last_message, "content", "") or ""
    if any(kw in content for kw in CALC_KEYWORDS):
        return "calc"

    # 3. 默认走 writer
    return "writer"


def build_graph():
    """构建并编译主图。"""
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

    conn = sqlite3.connect("checkpoints.db", check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return graph.compile(checkpointer=checkpointer)


app = build_graph()
