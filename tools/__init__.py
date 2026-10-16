from tools.calculator import calculate
from tools.database import query_database
from tools.database_admin import delete_employee
from tools.internal_api import INTERNAL_API_TOOLS
from tools.mcp_bridge import MCP_TOOLS
from tools.search import search_web
from tools.weather import get_weather

# 本地工具
LOCAL_TOOLS = [
    get_weather,
    calculate,
    search_web,
    query_database,
    delete_employee,
    *INTERNAL_API_TOOLS,
]

# 合并：本地 + MCP
ALL_TOOLS = LOCAL_TOOLS + MCP_TOOLS

# 工具名 → 工具对象
TOOL_MAP = {t.name: t for t in ALL_TOOLS}

# ---------- 敏感工具登记表 ----------
# 会改动数据/有副作用的工具必须在这里登记。闸门在**执行层**统一生效
# （agent/nodes.py 的 _execute_tool 会拒绝未登记放行的敏感工具），
# 而不是只在 info_node 的循环里判断，避免"换个节点就能绕过"。
# 新增危险工具时忘记登记会被 tests/test_sensitive_gate.py 挡住。
SENSITIVE_TOOL_NAMES = frozenset({"delete_employee"})


def is_sensitive_tool(name: str) -> bool:
    """工具是否属于需要人工确认的敏感操作。"""
    return name in SENSITIVE_TOOL_NAMES
