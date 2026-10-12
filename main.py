"""多工具 AI 助手 —— 对外唯一入口。

提供两个函数：
- run_agent(user_input, thread_id)   首次调用
- resume_agent(answer, thread_id)    敏感操作确认后恢复

使用方式：
    from main import run_agent, resume_agent

    result = run_agent("北京天气怎么样？")
    if result.startswith("[NEED_CONFIRM]"):
        # 需要用户确认，提取确认信息展示给用户
        print(result)
        answer = input("请输入 (yes/no): ")
        result = resume_agent(answer)
    print(result)
"""

import sys  # noqa: F401

from langchain_core.messages import HumanMessage
from langgraph.types import Command

from agent.graph import app
from utils.logger import get_logger

# 中断标记前缀。调用方用它判断是否触发了敏感操作确认
CONFIRM_PREFIX = "[NEED_CONFIRM]"
logger = get_logger(__name__)


def run_agent(user_input: str, thread_id: str = "default") -> str:
    """首次调用 Agent。

    正常返回：Agent 的最终回答。
    触发敏感操作：返回以 [NEED_CONFIRM] 开头的字符串，后面是确认提示。
    """
    logger.info(f"[run_agent] 用户输入: {user_input}, thread_id={thread_id}")
    config = {"configurable": {"thread_id": thread_id}}

    result = app.invoke(
        {"messages": [HumanMessage(content=user_input)]},
        config=config,
    )

    # 检查是否触发中断
    interrupt_info = result.get("__interrupt__")
    if interrupt_info:
        prompt = interrupt_info[0].value
        logger.warning(f"[run_agent] 触发中断: {prompt}")
        return f"{CONFIRM_PREFIX} {prompt}"

    # 没有中断，正常返回
    answer = result["messages"][-1].content
    logger.info(f"[run_agent] 返回回答: {answer[:100]}")  # ← 加
    return answer


def resume_agent(answer: str, thread_id: str = "default") -> str:
    """敏感操作确认后恢复执行。

    参数：
    - answer: "yes" 表示同意，"no" 表示拒绝，也可以是其他自定义文本
    - thread_id: 必须和首次调用一致，否则找不到中断状态

    返回：Agent 的最终回答。
    """
    config = {"configurable": {"thread_id": thread_id}}

    result = app.invoke(
        Command(resume=answer),
        config=config,
    )

    # 恢复后也可能再次中断（如果还有别的敏感操作）
    interrupt_info = result.get("__interrupt__")
    if interrupt_info:
        prompt = interrupt_info[0].value
        return f"{CONFIRM_PREFIX} {prompt}"

    return result["messages"][-1].content


if __name__ == "__main__":
    # 简单交互式测试
    result = run_agent("今天南昌天气怎么样")
    print(result)
