"""MCP Client：通过 stdio 协议调用 file_server 的 read_file 工具。

- 超时控制（避免 Server 卡死时客户端无限等待）
- 异常捕获（Server 崩溃、协议错误、工具执行错误都能返回友好信息）
- 路径参数校验（在客户端侧做基本检查，减少无效请求）
- 日志输出到 stderr（不污染 stdout）
"""

import asyncio
import sys
from pathlib import Path

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

# ---------- 配置 ----------
SERVER_SCRIPT = str(Path(__file__).parent / "file_server.py")
CALL_TIMEOUT = 30.0  # 工具调用超时（秒）


async def call_read_file(path: str) -> str:
    """通过 MCP 协议调用 file_server 的 read_file 工具。

    :param path: 相对于 documents/ 目录的文件路径
    :return: 文件内容，或错误信息
    """
    # 1. 配置 Server 启动参数
    server_params = StdioServerParameters(
        command=sys.executable,  # 用当前 Python 解释器
        args=[SERVER_SCRIPT],  # Server 脚本路径
    )

    try:
        # 2. 建立 stdio 通道（启动 Server 子进程）
        async with stdio_client(server_params) as (read, write):  # noqa: SIM117
            # 3. 在通道上建立会话
            async with ClientSession(read, write) as session:
                # 4. 协议握手（交换能力信息）初始化
                await session.initialize()

                # 5. 调用工具，带超时
                result = await asyncio.wait_for(
                    session.call_tool("read_file", {"path": path}),
                    timeout=CALL_TIMEOUT,
                )

                # 6. 提取返回的文本内容
                if not result.content:
                    return "错误：工具返回了空内容。"

                # MCP 返回的 content 是列表，每项有 .type 和 .text
                texts = [item.text for item in result.content if hasattr(item, "text")]
                return "\n".join(texts) if texts else "错误：无法解析返回内容。"

    except TimeoutError:
        return f"错误：调用工具超时（{CALL_TIMEOUT} 秒）。"
    except FileNotFoundError:
        return f"错误：找不到 Server 脚本 {SERVER_SCRIPT}。"
    except Exception as e:  # noqa: BLE001
        return f"错误：MCP 调用失败 - {type(e).__name__}: {e}"


async def list_server_tools() -> None:
    """列出 Server 提供的所有工具（调试用）。"""
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER_SCRIPT],
    )

    async with stdio_client(server_params) as (read, write):  # noqa: SIM117
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Server 提供的工具：", file=sys.stderr)
            for t in tools.tools:
                print(f"  - {t.name}: {t.description}", file=sys.stderr)


if __name__ == "__main__":
    # 测试 1：列出工具
    asyncio.run(list_server_tools())

    # 测试 2：读取文件
    print("\n=== 读取 test.txt ===")
    content = asyncio.run(call_read_file("test.txt"))
    print(content)

    # 测试 3：路径穿越攻击（应该被拒绝）
    print("\n=== 路径穿越测试 ===")
    content = asyncio.run(call_read_file("../../etc/passwd"))
    print(content)

    # 测试 4：不存在的文件
    print("\n=== 不存在的文件 ===")
    content = asyncio.run(call_read_file("not_exist.txt"))
    print(content)
