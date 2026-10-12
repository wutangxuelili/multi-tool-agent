"""LangGraph 主图的状态定义。"""

from typing import TypedDict


class State(TypedDict):
    """Agent 图的共享状态。

    字段说明：
    - messages: 完整对话历史（含用户输入、AI 回复、工具结果）
    - pending_tool: 待确认的敏感操作，没有则为 None
    - needs_calc: 是否需要进入计算阶段，由 info_agent 设置
    """

    messages: list
    pending_tool: dict | None
    needs_calc: bool
