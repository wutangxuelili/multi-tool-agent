"""LLM 客户端单例。

只对外暴露 get_llm()，返回一个未绑定工具的 ChatOpenAI 实例。
各 Agent 节点根据自己的职责，用 .bind_tools() 绑定不同的工具。

重要：实例是**惰性创建**的（第一次真正要用 LLM 时才读环境变量并建对象）。
这样即使没有 `.env`，也能 `import llm_client` / `import agent.graph`，
CI 里就可以无密钥地导入并测试图结构；缺失配置时报错信息也明确指向 .env。
"""

import os
import threading

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

from utils.logger import get_logger

load_dotenv()

logger = get_logger(__name__)

# 必需的环境变量（缺失时给出可操作的报错，而不是 pydantic 的 None 校验错误）
REQUIRED_ENV = ("LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")

_llm = None
_lock = threading.Lock()


def missing_env() -> list[str]:
    """返回缺失的必需环境变量名列表。"""
    return [name for name in REQUIRED_ENV if not os.getenv(name)]


def get_llm() -> ChatOpenAI:
    """返回 ChatOpenAI 单例（惰性、线程安全）。"""
    global _llm
    if _llm is None:
        with _lock:
            if _llm is None:
                absent = missing_env()
                if absent:
                    raise RuntimeError(
                        "缺少必需的环境变量："
                        + ", ".join(absent)
                        + "。请复制 .env.example 为 .env 并填写（见 README「配置 .env」）。"
                    )

                #   The `reasoning_content` in the thinking mode must be passed back to the API.
                # 因此默认关闭思考模式；如需开启，设 LLM_THINKING=adaptive 或 enabled。
                thinking = os.getenv("LLM_THINKING", "disabled")
                _llm = ChatOpenAI(
                    base_url=os.getenv("LLM_BASE_URL"),
                    api_key=os.getenv("LLM_API_KEY"),
                    model=os.getenv("LLM_MODEL"),
                    extra_body={"thinking": {"type": thinking}},
                )
                logger.info(
                    "[LLM] base_url=%s, model=%s, thinking=%s",
                    os.getenv("LLM_BASE_URL"),
                    os.getenv("LLM_MODEL"),
                    thinking,
                )
    return _llm


def reset_llm() -> None:
    """丢弃缓存的单例（测试或运行时改配置后使用）。"""
    global _llm
    with _lock:
        _llm = None
