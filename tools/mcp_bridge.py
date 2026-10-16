"""MCP 工具桥接层。

把 MCP Server 提供的工具包装成 LangChain @tool，
使其能注册进 TOOL_MAP，被 Agent 统一调用。

关于异步桥接：MCP Client 是异步的，而 LangGraph 的节点是同步的。
直接在同步函数里 `asyncio.run()` 在"已有事件循环"的宿主里会直接报错
（FastAPI / Jupyter / 某些 MCP 宿主都是这种情况），所以这里做了分流：
没有运行中的循环就用 `asyncio.run()`，有就把协程丢到独立线程里跑。
"""

import asyncio
import sys
import threading

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from mcp_servers.client import call_read_file

# ---------- MCP 工具的 Pydantic 参数模型 ----------


class ReadFileArgs(BaseModel):
    path: str = Field(
        min_length=1,
        description="相对于 documents/ 目录的文件路径，例如 test.txt",
    )


def run_coroutine_sync(coro):
    """在同步上下文里执行协程，兼容"当前已有事件循环"的情况。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 常规情况：当前线程没有事件循环
        return asyncio.run(coro)

    # 当前线程已在事件循环中：另起一个线程跑，避免 asyncio.run() 抛
    # "asyncio.run() cannot be called from a running event loop"
    box: dict = {}

    def _worker() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except BaseException as e:  # noqa: BLE001 - 原样回传给调用方
            box["error"] = e

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join()

    if "error" in box:
        raise box["error"]
    return box.get("result")


# ---------- MCP 工具包装 ----------


@tool(args_schema=ReadFileArgs)
def read_file_mcp(path: str) -> str:
    """通过 MCP 协议读取 documents/ 目录下的文件内容。支持 txt、md 等文本格式。"""
    try:
        return run_coroutine_sync(call_read_file(path))
    except Exception as e:  # noqa: BLE001
        print(f"[MCP Bridge] 调用失败: {e}", file=sys.stderr)
        return f"错误：MCP 工具调用失败 - {type(e).__name__}: {e}"


# ---------- 对外的 MCP 工具列表 ----------

MCP_TOOLS = [read_file_mcp]
