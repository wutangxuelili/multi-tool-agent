import os

from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from tavily import TavilyClient

load_dotenv()


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, description="搜索关键词，例如：Python 教程")


_client = None


def get_search_client() -> TavilyClient:
    """返回 Tavily 搜索客户端单例。"""
    global _client
    if _client is None:
        _client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    return _client


@tool(args_schema=SearchArgs)
def search_web(query: str) -> str:
    """搜索互联网，返回与关键词相关的摘要。"""
    try:
        args = SearchArgs.model_validate({"query": query})
    except Exception as e:  # noqa: BLE001
        return f"参数错误：{e}"

    try:
        client = get_search_client()
        response = client.search(args.query, max_results=3)
    except Exception as e:  # noqa: BLE001
        return f"搜索失败：{e}"

    results = response.get("results", [])
    if not results:
        return f"关于「{args.query}」没有找到相关结果。"

    parts = [f"关于「{args.query}」的搜索结果："]
    for i, item in enumerate(results, start=1):
        title = item.get("title", "无标题")
        content = item.get("content", "")[:200]
        url = item.get("url", "")
        parts.append(f"{i}. {title}\n   {content}\n   来源：{url}")

    return "\n\n".join(parts)


if __name__ == "__main__":
    print("name:", search_web.name)
    print("description:", search_web.description)
    print("args_schema:", search_web.args_schema.model_json_schema())
    print("\n调用结果：")
    print(search_web.invoke({"query": "Python 教程"}))
    print("\n--- 空字符串测试 ---")
    print(search_web.invoke({"query": ""}))
