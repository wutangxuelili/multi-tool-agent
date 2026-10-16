"""工具层与内部 API 的边界测试（不需要网络/API Key）。

覆盖几个"缺配置/边界输入"的真实故障点：
- 天气工具在没配置 HEFENG_* 时给出可操作提示，而不是拼出 `https://None/...`；
- 搜索工具在缺 TAVILY_API_KEY 时同理；
- 内部 API 工具的 base url 在**调用时**读取环境变量；
- MCP 桥接在"已有事件循环"的宿主里也能工作（旧实现在 FastAPI/Jupyter 下必失败）；
- 内部 API 的 limit 有上界（超出返回 422）。
"""

import asyncio

import pytest
import requests
from fastapi.testclient import TestClient

from internal_api import server as api_server
from tools import internal_api, mcp_bridge, search, weather

# ---------- 天气 ----------


def test_weather_reports_missing_config(monkeypatch):
    monkeypatch.delenv("HEFENG_API_HOST", raising=False)
    monkeypatch.delenv("HEFENG_API_KEY", raising=False)
    result = weather.get_weather.invoke({"city": "北京"})
    assert "未配置天气接口" in result
    assert "None" not in result


def test_weather_rejects_empty_city_at_tool_boundary():
    """空参数在工具边界被 args_schema 拦下；执行层负责把它转成可读文本。

    也就是说：参数校验有两层——pydantic 在入口拦非法输入，
    `_execute_tool` 保证任何异常都不会炸穿整张图。
    """
    from pydantic import ValidationError

    from agent import nodes

    with pytest.raises(ValidationError):
        weather.get_weather.invoke({"city": ""})
    assert "工具执行错误" in nodes._execute_tool("get_weather", {"city": ""})


def test_weather_handles_missing_now_field(monkeypatch):
    """接口返回 code=200 但没有 now 字段时不能 KeyError。"""
    monkeypatch.setenv("HEFENG_API_HOST", "example.invalid")
    monkeypatch.setenv("HEFENG_API_KEY", "k")

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": "200"}

    monkeypatch.setattr(weather, "_lookup_location_id", lambda city, host, key: "101")
    monkeypatch.setattr(weather.requests, "get", lambda *a, **kw: _FakeResponse())

    result = weather.get_weather.invoke({"city": "北京"})
    assert "未返回实时数据" in result


# ---------- 搜索 ----------


def test_search_reports_missing_api_key(monkeypatch):
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(search, "_client", None)
    result = search.search_web.invoke({"query": "Python"})
    assert "TAVILY_API_KEY" in result


def test_search_max_results_is_configurable(monkeypatch):
    monkeypatch.setenv("SEARCH_MAX_RESULTS", "7")
    assert search.max_results() == 7
    monkeypatch.setenv("SEARCH_MAX_RESULTS", "not-a-number")
    assert search.max_results() == search.DEFAULT_MAX_RESULTS


# ---------- 内部 API 工具 ----------


def test_internal_api_base_url_is_read_at_call_time(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_BASE", "http://first:8001")
    assert internal_api.base_url() == "http://first:8001"
    monkeypatch.setenv("INTERNAL_API_BASE", "http://second:9002")
    assert internal_api.base_url() == "http://second:9002"


def test_internal_api_reports_connection_error(monkeypatch):
    """连不上内部 API 时给出可操作提示。

    这里**打桩抛异常**而不是真去连 `127.0.0.1:1`：真实网络行为在不同环境里
    可能是"立刻拒绝"（ConnectionError）也可能是"卡到超时"（ConnectTimeout），
    后者会让测试变成环境相关的 flaky 用例。
    """

    def _refused(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(internal_api.requests, "get", _refused)
    result = internal_api.list_announcements.invoke({"limit": 1})
    assert "无法连接内部 API" in result


# ---------- 内部 API 服务本身 ----------


@pytest.fixture
def api_client():
    return TestClient(api_server.app)


def test_api_health(api_client):
    assert api_client.get("/health").json() == {"status": "ok"}


def test_api_announcements_default(api_client):
    payload = api_client.get("/announcements").json()
    assert payload["total"] == 4
    assert len(payload["announcements"]) == 4


def test_api_rejects_out_of_range_limit(api_client):
    assert api_client.get("/announcements", params={"limit": 999999}).status_code == 422
    assert api_client.get("/announcements", params={"limit": 0}).status_code == 422


def test_api_filters_by_category(api_client):
    payload = api_client.get("/announcements", params={"category": "培训"}).json()
    assert [a["title"] for a in payload["announcements"]] == ["新员工培训"]


def test_api_unknown_announcement_returns_404(api_client):
    assert api_client.get("/announcements/999").status_code == 404


# ---------- MCP 桥接的异步兼容 ----------


def test_run_coroutine_sync_without_loop():
    async def work():
        return "sync-ok"

    assert mcp_bridge.run_coroutine_sync(work()) == "sync-ok"


def test_run_coroutine_sync_inside_running_loop():
    """在已有事件循环里也必须能跑（旧实现直接 asyncio.run → RuntimeError）。"""

    async def work():
        return "loop-ok"

    async def caller():
        return mcp_bridge.run_coroutine_sync(work())

    assert asyncio.run(caller()) == "loop-ok"


def test_run_coroutine_sync_propagates_exception():
    async def boom():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        mcp_bridge.run_coroutine_sync(boom())


def test_read_file_mcp_returns_error_string_for_bad_path():
    result = mcp_bridge.read_file_mcp.invoke({"path": "../etc/passwd"})
    assert "不允许访问" in result
