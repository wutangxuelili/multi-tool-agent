"""多工具 AI 助手 —— 对外唯一入口。

提供三个函数：
- new_thread_id(prefix)              生成一个隔离的会话 ID
- run_agent(user_input, thread_id)   首次调用（thread_id 必填）
- resume_agent(answer, thread_id)    敏感操作确认后恢复

为什么 thread_id 是必填参数：LangGraph 按 thread_id 隔离 checkpoint，
默认值（旧实现是 "default"）会让所有调用方共用同一份中断现场，
A 用户触发的待确认删除可能被 B 用户的确认答复执行掉。交给调用方
显式分配会话 ID，是这里唯一安全的选择。

使用方式：
    from main import CONFIRM_PREFIX, new_thread_id, resume_agent, run_agent

    thread_id = new_thread_id("user-42")          # 每个用户/会话一个
    result = run_agent("北京天气怎么样？", thread_id=thread_id)
    while result.startswith(CONFIRM_PREFIX):
        # 需要人工确认，把确认信息展示给用户后再恢复（thread_id 必须一致）
        print(result)
        result = resume_agent(input("请输入 (yes/no): "), thread_id=thread_id)
    print(result)
"""

import uuid

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent.graph import app
from utils.logger import get_logger

# 中断标记前缀。调用方用它判断是否触发了敏感操作确认
CONFIRM_PREFIX = "[NEED_CONFIRM]"
# 错误标记前缀（例如对没有待确认操作的 thread 调用了 resume_agent）
ERROR_PREFIX = "[ERROR]"

logger = get_logger(__name__)


def new_thread_id(prefix: str = "thread") -> str:
    """生成一个新的会话 ID（thread_id）。

    :param prefix: 便于人读的前缀，例如 "user-42"、"cli"
    """
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _message_text(message) -> str:
    """把消息内容转成字符串（思考模式下 content 可能是分段列表）。"""
    content = getattr(message, "content", message)
    return content if isinstance(content, str) else str(content)


def has_pending_interrupt(thread_id: str) -> bool:
    """该 thread_id 上是否有等待人工确认的中断。"""
    snapshot = app.get_state(_config(thread_id))
    tasks = getattr(snapshot, "tasks", ()) or ()
    return any(getattr(task, "interrupts", None) for task in tasks)


def run_agent(user_input: str, thread_id: str) -> str:
    """首次调用 Agent。

    :param thread_id: 会话 ID，由调用方分配并保存（恢复时必须传同一个）。
        可用 new_thread_id() 生成。

    正常返回：Agent 的最终回答。
    触发敏感操作：返回以 [NEED_CONFIRM] 开头的字符串，后面是确认提示，
        调用方应把提示展示给用户，再用 resume_agent() 传回答复。
    """
    logger.info(f"[run_agent] 用户输入: {user_input}, thread_id={thread_id}")

    result = app.invoke(
        {"messages": [HumanMessage(content=user_input)]},
        config=_config(thread_id),
    )

    # 检查是否触发中断
    interrupt_info = result.get("__interrupt__")
    if interrupt_info:
        prompt = interrupt_info[0].value
        logger.warning(f"[run_agent] 触发中断: {prompt}")
        return f"{CONFIRM_PREFIX} {prompt}"

    answer = _message_text(result["messages"][-1])
    logger.info(f"[run_agent] 返回回答: {answer[:100]}")
    return answer


def resume_agent(answer: str, thread_id: str) -> str:
    """敏感操作确认后恢复执行。

    参数：
    - answer: "yes"（含 y / 是 / 确认 / 同意）表示同意，其他一律视为拒绝
    - thread_id: 必须和首次调用一致，否则找不到中断状态

    返回：Agent 的最终回答；若该 thread 上没有待确认操作，返回 [ERROR] 开头的说明。
    """
    if not has_pending_interrupt(thread_id):
        logger.warning(f"[resume_agent] thread_id={thread_id} 上没有待确认操作")
        return (
            f"{ERROR_PREFIX} thread_id={thread_id} 上没有待确认的敏感操作，无法恢复。"
            "请确认 thread_id 与触发中断的那次调用完全一致（见 README 排障第 4 条）。"
        )

    result = app.invoke(Command(resume=answer), config=_config(thread_id))

    # 恢复后也可能再次中断（如果还有别的敏感操作）
    interrupt_info = result.get("__interrupt__")
    if interrupt_info:
        prompt = interrupt_info[0].value
        logger.warning(f"[resume_agent] 再次触发中断: {prompt}")
        return f"{CONFIRM_PREFIX} {prompt}"

    return _message_text(result["messages"][-1])


if __name__ == "__main__":
    # 简单交互式测试：演示"提问 → 需要确认 → 回复 → 继续"的完整闭环
    cli_thread = new_thread_id("cli")
    print(f"[demo] thread_id={cli_thread}")

    reply = run_agent("今天南昌天气怎么样", thread_id=cli_thread)
    print(reply)

    while reply.startswith(CONFIRM_PREFIX):
        reply = resume_agent(input("请输入 (yes/no): ").strip(), thread_id=cli_thread)
        print(reply)
