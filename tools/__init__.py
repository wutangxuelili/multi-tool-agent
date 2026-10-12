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
