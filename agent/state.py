"""LangGraph 主图的状态定义。"""

from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class State(TypedDict):
    """Agent 图的共享状态。

    字段说明：
    - messages: 完整对话历史（含用户输入、AI 回复、工具结果）。
      **必须挂 add_messages reducer**：LangGraph 会把 `invoke()` 的输入当作一次
      state update 应用；没有 reducer 时它是"整字段覆盖"，第二次 `run_agent()`
      传入的新 HumanMessage 会把 checkpoint 里的历史顶掉，多轮对话就丢了上下文。
      挂了 reducer 之后，节点只需要返回**本轮新增**的消息。
    - pending_tool: 待确认的敏感操作，没有则为 None

    说明：早期版本还有一个 `needs_calc` 字段，注释写着"由 info_agent 设置"，
    但全项目从未读写（典型的"声明了却没接线"），已删除；是否需要计算现在由
    `agent/graph.py` 的 `route_after_info` 依据用户提问判断。
    """

    messages: Annotated[list[AnyMessage], add_messages]
    pending_tool: dict | None
