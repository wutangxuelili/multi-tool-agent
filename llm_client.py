"""LLM 客户端单例。

只对外暴露 get_llm()，返回一个未绑定工具的 ChatOpenAI 实例。
各 Agent 节点根据自己的职责，用 .bind_tools() 绑定不同的工具。
"""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

_llm = None


def get_llm() -> ChatOpenAI:
    """返回 ChatOpenAI 单例。"""
    global _llm
    if _llm is None:
        #   The `reasoning_content` in the thinking mode must be passed back to the API.
        # 因此默认关闭思考模式；如需开启，设 LLM_THINKING=adaptive 或 enabled。
        thinking = os.getenv("LLM_THINKING", "disabled")
        _llm = ChatOpenAI(
            base_url=os.getenv("LLM_BASE_URL"),
            api_key=os.getenv("LLM_API_KEY"),
            model=os.getenv("LLM_MODEL"),
            extra_body={"thinking": {"type": thinking}},
        )
        print(
            f"[LLM] base_url={os.getenv('LLM_BASE_URL')}, "
            f"model={os.getenv('LLM_MODEL')}, thinking={thinking}"
        )
    return _llm
