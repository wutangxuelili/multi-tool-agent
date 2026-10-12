"""MCP 工具桥接层。

把 MCP Server 提供的工具包装成 LangChain @tool，
使其能注册进 TOOL_MAP，被 Agent 统一调用。
"""

import asyncio
import sys

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from mcp_servers.client import call_read_file

# ---------- MCP 工具的 Pydantic 参数模型 ----------


class ReadFileArgs(BaseModel):
    path: str = Field(
        min_length=1,
        description="相对于 documents/ 目录的文件路径，例如 test.txt",
    )


# ---------- MCP 工具包装 ----------


@tool(args_schema=ReadFileArgs)
def read_file_mcp(path: str) -> str:
    """通过 MCP 协议读取 documents/ 目录下的文件内容。支持 txt、md 等文本格式。"""
    try:
        # MCP Client 是异步的，用 asyncio.run 在同步函数里驱动
        return asyncio.run(call_read_file(path))
    except RuntimeError as e:
        # asyncio.run 在已有事件循环中会报错
        print(f"[MCP Bridge] 事件循环冲突: {e}", file=sys.stderr)
        return f"错误：无法在异步环境中调用 MCP 工具 - {e}"
    except Exception as e:  # noqa: BLE001
        print(f"[MCP Bridge] 调用失败: {e}", file=sys.stderr)
        return f"错误：MCP 工具调用失败 - {type(e).__name__}: {e}"


# ---------- 对外的 MCP 工具列表 ----------

MCP_TOOLS = [read_file_mcp]
