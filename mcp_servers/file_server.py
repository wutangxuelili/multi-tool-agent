"""一个极简的 MCP Server，暴露 read_file 工具。

安全边界：
- 白名单根目录 = 本文件所在包的上层目录下的 `documents/`，
  **用 `__file__` 解析而不是当前工作目录**，因此不必依赖宿主设置 cwd；
- 用 `Path.resolve()` + `Path.is_relative_to()` 做**真实路径**判定，
  而不是字符串前缀匹配——后者会让 `../documents_evil/x` 这类
  与白名单目录共享前缀的兄弟目录蒙混过关。
"""

from pathlib import Path

from mcp.server import MCPServer

# 创建 MCP Server 实例
mcp = MCPServer("file-reader")

# 允许读取的根目录（真实路径，不随 cwd 变化）
ALLOWED_DIR = (Path(__file__).resolve().parent.parent / "documents").resolve()

# 单次返回的最大字符数
MAX_LEN = 5000


def resolve_within_allowed_dir(path: str) -> Path | None:
    """把请求路径解析为白名单目录内的真实路径；越界或非法则返回 None。

    `resolve()` 会消掉 `..`、`.` 并展开符号链接，因此：
    - `../documents_evil/secret.txt` → 白名单外 → None（旧实现会放行）
    - `/etc/passwd`、`C:\\Windows\\win.ini`、UNC 路径 → 白名单外 → None
    - 指向目录外的符号链接 → 白名单外 → None
    """
    if not path or not isinstance(path, str):
        return None
    try:
        target = (ALLOWED_DIR / path).resolve()
    except (OSError, RuntimeError, ValueError):
        # 非法字符、路径过长、符号链接成环等
        return None
    if not target.is_relative_to(ALLOWED_DIR):
        return None
    return target


@mcp.tool()
def read_file(path: str) -> str:
    """读取 documents/ 目录下指定路径的文件内容。

    :param path: 相对于 documents/ 目录的文件路径
    """
    # 1. 解析 + 白名单校验（真实路径判定，防目录穿越）
    full_path = resolve_within_allowed_dir(path)
    if full_path is None:
        return f"错误：不允许访问 {path}，只能读取 documents/ 目录下的文件。"

    # 2. 检查文件是否存在
    if not full_path.is_file():
        return f"错误：文件不存在 {path}"

    # 3. 读取内容
    try:
        content = full_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"错误：{path} 不是 UTF-8 文本文件，暂不支持读取。"
    except OSError as e:
        return f"读取失败：{e}"

    # 4. 限制返回长度
    if len(content) > MAX_LEN:
        content = content[:MAX_LEN] + f"\n...(已截断，原文共 {len(content)} 字)"

    return content


if __name__ == "__main__":
    mcp.run()
