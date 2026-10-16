"""敏感工具登记的守卫测试。

新增"会改数据"的工具时，如果忘了在 `tools/__init__.py` 的
SENSITIVE_TOOL_NAMES 里登记，这些用例会失败——把"靠人记得"变成"机器记得"。
"""

from langchain_core.tools import BaseTool

from agent import nodes
from tools import SENSITIVE_TOOL_NAMES, TOOL_MAP, database_admin, is_sensitive_tool


def test_registered_sensitive_names_exist_in_tool_map():
    assert set(TOOL_MAP) >= SENSITIVE_TOOL_NAMES


def test_every_database_admin_tool_is_registered_as_sensitive():
    """tools/database_admin.py 里的工具都会改数据，必须全部登记。"""
    tool_names = {
        value.name
        for value in vars(database_admin).values()
        if isinstance(value, BaseTool)
    }
    assert tool_names, "database_admin 模块里至少应有一个工具"
    unregistered = tool_names - SENSITIVE_TOOL_NAMES
    assert not unregistered, f"这些工具会改数据但未登记为敏感操作: {sorted(unregistered)}"


def test_delete_employee_is_sensitive():
    assert is_sensitive_tool("delete_employee")


def test_read_only_tools_are_not_sensitive():
    for name in ("query_database", "get_weather", "search_web", "calculate"):
        assert not is_sensitive_tool(name), f"{name} 不应被标记为敏感操作"


def test_info_node_binds_the_sensitive_tool_but_never_executes_it_directly():
    """敏感工具必须绑给 info_node（否则模型无法发起请求），但执行要走确认。"""
    assert "delete_employee" in nodes.INFO_TOOL_NAMES
    assert "delete_employee" not in nodes.CALC_TOOL_NAMES
    assert "拒绝执行" in nodes._execute_tool("delete_employee", {"employee_id": 1})
