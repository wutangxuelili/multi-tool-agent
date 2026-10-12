"""LangGraph 主图的节点函数。

四个节点：
- info_node    信息收集（含敏感操作检测）
- calc_node    数学计算
- writer_node  撰写最终回答
- confirm_node 敏感操作确认（触发 interrupt）
"""

import time

from langchain_core.messages import (  # noqa: F401
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.types import interrupt

from agent.prompts import (
    CALC_AGENT_PROMPT,
    INFO_AGENT_PROMPT,
    WRITER_AGENT_PROMPT,
)
from agent.state import State
from llm_client import get_llm
from tools import ALL_TOOLS, TOOL_MAP
from utils.logger import get_logger

# ---------- 配置 ----------
MAX_INFO_ROUNDS = 5
MAX_CALC_ROUNDS = 3
SENSITIVE_TOOLS = {"delete_employee"}
logger = get_logger(__name__)
INFO_TOOL_NAMES = {
    "get_weather",
    "search_web",
    "query_database",
    "delete_employee",
    "read_file_mcp",
    "list_announcements",
}
CALC_TOOL_NAMES = {"calculate"}

# 按职责筛选工具
INFO_TOOLS = [t for t in ALL_TOOLS if t.name in INFO_TOOL_NAMES]
CALC_TOOLS = [t for t in ALL_TOOLS if t.name in CALC_TOOL_NAMES]

# 绑定了各自工具的 LLM
_llm = get_llm()
info_llm = _llm.bind_tools(INFO_TOOLS)
calc_llm = _llm.bind_tools(CALC_TOOLS)


def info_node(state: State) -> dict:
    """信息收集节点。"""
    messages = [SystemMessage(content=INFO_AGENT_PROMPT), *state["messages"]]
    original_len = len(messages)
    pending = None
    start_time = time.time()

    logger.info(f"[info_node] 开始，历史消息数={len(state['messages'])}")

    for round_num in range(MAX_INFO_ROUNDS):
        logger.debug(f"[info_node] 第 {round_num + 1} 轮")

        # ---------- 步骤 1：调用 LLM ----------
        response = info_llm.invoke(messages)
        messages.append(response)

        # ---------- 步骤 2：记录 LLM 的推理 ----------
        if response.content:
            logger.info(f"[info_node] LLM 推理: {response.content[:200]}")

        # ---------- 步骤 3：判断是否需要工具 ----------
        if not response.tool_calls:
            logger.info("[info_node] 无工具调用，信息收集完成")
            break

        # ---------- 步骤 4：遍历所有工具调用 ----------
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            logger.info(f"[info_node] 调用工具: {tool_name}, 参数: {tool_args}")

            # 4.1 敏感操作：不执行，记录下来
            if tool_name in SENSITIVE_TOOLS:
                pending = tool_call
                logger.warning(f"[info_node] 敏感操作，等待用户确认: {tool_name}")
                continue

            # 4.2 普通工具：执行并记录耗时
            tool_start = time.time()
            try:
                result = TOOL_MAP[tool_name].invoke(tool_args)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[info_node] 工具 {tool_name} 执行失败: {e}")
                result = f"工具执行错误：{e}"
            tool_elapsed = time.time() - tool_start

            logger.info(
                f"[info_node] 工具结果: {str(result)[:200]}, 耗时: {tool_elapsed:.2f}s"
            )
            messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

        # ---------- 步骤 5：如果有待确认的敏感操作，跳出循环 ----------
        if pending:
            break

    elapsed = time.time() - start_time
    logger.info(f"[info_node] 结束，耗时={elapsed:.2f}s, 待确认={bool(pending)}")

    # 只把本轮新增的消息写回 state，避免把注入的 SystemMessage 重复存进历史
    return {
        "messages": state["messages"] + messages[original_len:],
        "pending_tool": pending,
    }


def calc_node(state: State) -> dict:
    """计算节点。"""
    messages = [
        SystemMessage(content=CALC_AGENT_PROMPT),
        *state["messages"],
    ]
    original_len = len(messages)

    for _ in range(MAX_CALC_ROUNDS):
        response = calc_llm.invoke(messages)
        messages.append(response)
        if not response.tool_calls:
            break
        for tool_call in response.tool_calls:
            result = TOOL_MAP[tool_call["name"]].invoke(tool_call["args"])
            messages.append(ToolMessage(content=result, tool_call_id=tool_call["id"]))

    new_messages = messages[original_len:]
    return {"messages": state["messages"] + new_messages}


def writer_node(state: State) -> dict:
    """撰写节点。"""
    messages = [
        SystemMessage(content=WRITER_AGENT_PROMPT),
        *state["messages"],
    ]
    response = _llm.invoke(messages)
    return {"messages": state["messages"] + [response]}


def confirm_node(state: State) -> dict:
    """敏感操作确认节点。"""
    pending = state.get("pending_tool")
    if not pending:
        return {}

    answer = interrupt(
        f"即将执行敏感操作：{pending['name']}，参数：{pending['args']}。确认吗？(yes/no)"
    )

    if answer == "yes":
        result = TOOL_MAP[pending["name"]].invoke(pending["args"])
    else:
        result = "用户取消了操作。"

    return {
        "messages": state["messages"]
        + [ToolMessage(content=result, tool_call_id=pending["id"])],
        "pending_tool": None,
    }
