"""一个极简的 MCP Server，暴露 read_file 工具。"""

import os

from mcp.server import MCPServer

# 创建 MCP Server 实例
mcp = MCPServer("file-reader")

# 允许读取的根目录（安全限制）
ALLOWED_DIR = os.path.abspath("documents")


@mcp.tool()
def read_file(path: str) -> str:
    """读取指定路径的文件内容。

    :param path: 相对于 documents/ 目录的文件路径
    """
    # 1. 拼接绝对路径
    full_path = os.path.abspath(os.path.join(ALLOWED_DIR, path))

    # 2. 安全校验：确保路径在允许的目录内
    if not full_path.startswith(ALLOWED_DIR):
        return f"错误：不允许访问 {path}，只能读取 documents/ 目录下的文件。"

    # 3. 检查文件是否存在
    if not os.path.isfile(full_path):
        return f"错误：文件不存在 {path}"

    # 4. 读取内容
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:  # noqa: BLE001
        return f"读取失败：{e}"

    # 5. 限制返回长度
    MAX_LEN = 5000
    if len(content) > MAX_LEN:
        content = content[:MAX_LEN] + f"\n...(已截断，原文共 {len(content)} 字)"

    return content


if __name__ == "__main__":
    mcp.run()
