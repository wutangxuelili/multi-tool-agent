"""内部 API 工具的 LangChain 包装。

把 internal_api/server.py 提供的 HTTP 接口包装成 @tool，
让 Agent 可以通过自然语言调用公司内部系统。
"""

import os

import requests
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# ---------- 配置 ----------
INTERNAL_API_BASE = os.getenv("INTERNAL_API_BASE", "http://localhost:8001")
REQUEST_TIMEOUT = 10  # 秒


# ---------- 参数模型 ----------


class ListAnnouncementsArgs(BaseModel):
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="最多返回几条公告，范围 1-20，默认 5",
    )
    category: str | None = Field(
        default=None,
        description="可选，按分类过滤。常见分类：活动、运维、培训、财务",
    )


# ---------- 工具实现 ----------


@tool(args_schema=ListAnnouncementsArgs)
def list_announcements(limit: int = 5, category: str | None = None) -> str:
    """查询公司内部公告。可以按分类过滤，返回公告标题、日期和内容摘要。"""
    # 1. 构造请求参数
    params = {"limit": limit}
    if category:
        params["category"] = category

    # 2. 发送请求
    try:
        resp = requests.get(
            f"{INTERNAL_API_BASE}/announcements",
            params=params,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return f"错误：内部 API 请求超时（{REQUEST_TIMEOUT} 秒）。"
    except requests.exceptions.ConnectionError:
        return f"错误：无法连接内部 API（{INTERNAL_API_BASE}）。请确认服务已启动。"
    except requests.exceptions.HTTPError as e:
        return f"错误：内部 API 返回 {e.response.status_code}。"
    except requests.exceptions.RequestException as e:
        return f"错误：请求失败 - {type(e).__name__}: {e}"

    # 3. 解析响应
    try:
        data = resp.json()
    except ValueError:
        return "错误：内部 API 返回的内容不是合法 JSON。"

    announcements = data.get("announcements", [])
    if not announcements:
        suffix = f"（分类：{category}）" if category else ""
        return f"没有找到公告{suffix}。"

    # 4. 格式化成 LLM 易读的文本
    lines = [f"共找到 {data.get('total', len(announcements))} 条公告："]
    for a in announcements:
        lines.append(
            f"\n【{a['id']}】{a['title']}（{a['date']}，{a['category']}）\n{a['content']}"
        )
    return "\n".join(lines)


# ---------- 对外工具列表 ----------

INTERNAL_API_TOOLS = [list_announcements]


if __name__ == "__main__":
    print("=== 默认查询（前 5 条）===")
    print(list_announcements.invoke({}))

    print("\n=== 按分类过滤 ===")
    print(list_announcements.invoke({"category": "培训"}))

    print("\n=== 限制数量 ===")
    print(list_announcements.invoke({"limit": 2}))

    print("\n=== 空结果 ===")
    print(list_announcements.invoke({"category": "不存在的分类"}))
