"""LangGraph 主图的节点函数。

四个节点：
- info_node    信息收集（含敏感操作检测）
- calc_node    数学计算
- writer_node  撰写最终回答
- confirm_node 敏感操作确认（触发 interrupt）

关于状态写入：`State.messages` 挂了 `add_messages` reducer，
因此所有节点只返回**本轮新增**的消息，不要自己拼接历史（旧实现四处手工
`state["messages"] + ...`，既啰嗦又是"多轮记忆失效"的病根）。
"""

import time

from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.types import interrupt

from agent.prompts import (
    CALC_AGENT_PROMPT,
    INFO_AGENT_PROMPT,
    WRITER_AGENT_PROMPT,
)
from agent.state import State
from llm_client import get_llm
from tools import (
    ALL_TOOLS,
    SENSITIVE_TOOL_NAMES,
    TOOL_MAP,
    is_sensitive_tool,
)
from utils.audit import record_sensitive_op
from utils.logger import get_logger
from utils.operator import operator_scope

# ---------- 配置 ----------
MAX_INFO_ROUNDS = 5
MAX_CALC_ROUNDS = 3
logger = get_logger(__name__)

# 兼容旧引用名；敏感工具清单的唯一事实来源在 tools/__init__.py
SENSITIVE_TOOLS = SENSITIVE_TOOL_NAMES

INFO_TOOL_NAMES = frozenset(
    {
        "get_weather",
        "search_web",
        "query_database",
        "delete_employee",
        "read_file_mcp",
        "list_announcements",
    }
)
CALC_TOOL_NAMES = frozenset({"calculate"})

# 判定"用户同意执行"的答复。旧实现只认字符串完全等于 "yes"，
# 用户输入 "Yes" / "确认" / "y" 会被静默当成取消，这里做归一化。
AFFIRMATIVE_ANSWERS = frozenset({"yes", "y", "是", "确认", "同意"})


def is_affirmative(answer) -> bool:
    """判断确认答复是否为"同意执行"。"""
    return str(answer).strip().lower() in AFFIRMATIVE_ANSWERS


def get_bound_llm(tool_names) -> object:
    """按职责筛选工具并绑定到 LLM。

    单独抽成函数有两个目的：
    1. LLM 惰性获取（模块导入不再要求存在 .env，CI 可以无密钥导入本模块）；
    2. 测试可以 monkeypatch 本函数注入脚本化的假 LLM，从而覆盖图级行为。
    """
    tools = [t for t in ALL_TOOLS if t.name in tool_names]
    return get_llm().bind_tools(tools)


def _execute_tool(tool_name: str, tool_args: dict, *, allow_sensitive: bool = False):
    """统一执行入口：异常不外泄，敏感工具默认拒绝。

    闸门放在执行层而不是只在 info_node 的循环里判断，
    这样即使某个节点（例如 calc_node）被诱导出敏感工具名，也执行不了。
    """
    if is_sensitive_tool(tool_name) and not allow_sensitive:
        logger.warning(f"[_execute_tool] 拒绝未确认的敏感操作: {tool_name}")
        return f"拒绝执行：{tool_name} 属于敏感操作，必须先经人工确认。"

    tool = TOOL_MAP.get(tool_name)
    if tool is None:
        return f"工具执行错误：未知工具 {tool_name}"

    try:
        return tool.invoke(tool_args)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[_execute_tool] 工具 {tool_name} 执行失败: {e}")
        return f"工具执行错误：{e}"


def _current_thread_id() -> str | None:
    """取当前运行的 thread_id；不在图运行上下文里时返回 None。"""
    try:
        from langgraph.config import get_config

        return get_config().get("configurable", {}).get("thread_id")
    except Exception:  # noqa: BLE001 - 不在运行时上下文
        return None


def info_node(state: State) -> dict:
    """信息收集节点。"""
    messages = [SystemMessage(content=INFO_AGENT_PROMPT), *state["messages"]]
    new_messages: list = []
    pending = None
    start_time = time.time()
    llm = get_bound_llm(INFO_TOOL_NAMES)

    logger.info(f"[info_node] 开始，历史消息数={len(state['messages'])}")

    for round_num in range(MAX_INFO_ROUNDS):
        logger.debug(f"[info_node] 第 {round_num + 1} 轮")

        # ---------- 步骤 1：调用 LLM ----------
        response = llm.invoke(messages)
        messages.append(response)
        new_messages.append(response)

        # ---------- 步骤 2：记录 LLM 的推理 ----------
        if response.content:
            logger.info(f"[info_node] LLM 推理: {str(response.content)[:200]}")

        # ---------- 步骤 3：判断是否需要工具 ----------
        if not response.tool_calls:
            logger.info("[info_node] 无工具调用，信息收集完成")
            break

        # ---------- 步骤 4：遍历所有工具调用 ----------
        for tool_call in response.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            logger.info(f"[info_node] 调用工具: {tool_name}, 参数: {tool_args}")

            # 4.1 敏感操作：不执行，交给 confirm_node
            if is_sensitive_tool(tool_name):
                if pending is None:
                    pending = tool_call
                    logger.warning(f"[info_node] 敏感操作，等待用户确认: {tool_name}")
                else:
                    # 同一轮出现多个敏感调用：一次只确认一个。其余必须显式回应，
                    # 否则历史里会留下"有 tool_call 没有 ToolMessage"的 AIMessage，
                    # 下一次请求会被 OpenAI 兼容端点判为 400。
                    logger.warning(f"[info_node] 本轮还有未确认的敏感操作: {tool_name}")
                    new_messages.append(
                        ToolMessage(
                            content=(
                                f"未执行：{tool_name} 未获确认（一次只处理一个敏感操作），"
                                "请在本轮确认完成后单独重新发起。"
                            ),
                            tool_call_id=tool_call["id"],
                        )
                    )
                continue

            # 4.2 普通工具：执行并记录耗时
            tool_start = time.time()
            result = _execute_tool(tool_name, tool_args)
            tool_elapsed = time.time() - tool_start
            msg = ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            messages.append(msg)
            new_messages.append(msg)

            logger.info(
                f"[info_node] 工具结果: {str(result)[:200]}, 耗时: {tool_elapsed:.2f}s"
            )

        # ---------- 步骤 5：有待确认的敏感操作就跳出循环 ----------
        if pending:
            break

    elapsed = time.time() - start_time
    logger.info(f"[info_node] 结束，耗时={elapsed:.2f}s, 待确认={bool(pending)}")

    # 只返回本轮新增的消息（SystemMessage 不入库，避免历史里堆系统提示）
    return {"messages": new_messages, "pending_tool": pending}


def calc_node(state: State) -> dict:
    """计算节点。"""
    messages = [SystemMessage(content=CALC_AGENT_PROMPT), *state["messages"]]
    new_messages: list = []
    llm = get_bound_llm(CALC_TOOL_NAMES)

    for _ in range(MAX_CALC_ROUNDS):
        response = llm.invoke(messages)
        messages.append(response)
        new_messages.append(response)
        if not response.tool_calls:
            break
        for tool_call in response.tool_calls:
            # calc_llm 只绑了 calculate，但模型仍可能幻觉出别的工具名：
            # 走统一执行器，未知工具/敏感工具都会被挡住而不是抛 KeyError。
            result = _execute_tool(tool_call["name"], tool_call["args"])
            msg = ToolMessage(content=str(result), tool_call_id=tool_call["id"])
            messages.append(msg)
            new_messages.append(msg)

    return {"messages": new_messages}


def writer_node(state: State) -> dict:
    """撰写节点。"""
    messages = [
        SystemMessage(content=WRITER_AGENT_PROMPT),
        *state["messages"],
    ]
    response = get_llm().invoke(messages)
    return {"messages": [response]}


def confirm_node(state: State) -> dict:
    """敏感操作确认节点。"""
    pending = state.get("pending_tool")
    if not pending:
        return {}

    # 防御损坏的 checkpoint：字段不全就没法挂起等确认，直接清掉并留日志，
    # 而不是抛 KeyError 把整张图炸掉。
    if not isinstance(pending, dict) or not {"name", "args", "id"} <= set(pending):
        logger.error(f"[confirm_node] pending_tool 结构不合法，已丢弃: {pending!r}")
        return {"pending_tool": None}

    tool_name = pending["name"]
    tool_args = pending["args"]
    answer = interrupt(f"即将执行敏感操作：{tool_name}，参数：{tool_args}。确认吗？(yes/no)")

    approved = is_affirmative(answer)
    thread_id = _current_thread_id()
    if approved:
        # 把"操作人"通过 ContextVar 传给工具（例如删除时写入归档表）
        with operator_scope(thread_id):
            result = _execute_tool(tool_name, tool_args, allow_sensitive=True)
    else:
        result = "用户取消了操作。"

    # 审计留痕：谁（thread_id）在什么时间批准/拒绝了什么操作、结果如何
    record_sensitive_op(
        tool=tool_name,
        args=tool_args,
        decision="approved" if approved else "rejected",
        answer=str(answer),
        result=str(result),
        thread_id=thread_id,
    )

    return {
        "messages": [ToolMessage(content=str(result), tool_call_id=pending["id"])],
        "pending_tool": None,
    }
