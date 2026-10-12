import os

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

load_dotenv()


class WeatherArgs(BaseModel):
    city: str = Field(min_length=1, description="城市名称，例如：北京")


def _lookup_location_id(city: str) -> str | None:
    """用城市名查询 LocationID。"""
    host = os.getenv("HEFENG_API_HOST")
    key = os.getenv("HEFENG_API_KEY")

    url = f"https://{host}/geo/v2/city/lookup"
    params = {"location": city}
    headers = {"X-QW-Api-Key": key}

    response = requests.get(url, params=params, headers=headers, timeout=10)
    response.raise_for_status()
    data = response.json()

    if data.get("code") != "200":
        return None
    locations = data.get("location", [])
    if not locations:
        return None
    return locations[0]["id"]


@tool(args_schema=WeatherArgs)
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。"""
    try:
        args = WeatherArgs.model_validate({"city": city})
    except Exception as e:  # noqa: BLE001
        return f"参数错误：{e}"

    try:
        location_id = _lookup_location_id(args.city)
        if not location_id:
            return f"未找到城市：{args.city}"

        host = os.getenv("HEFENG_API_HOST")
        key = os.getenv("HEFENG_API_KEY")

        url = f"https://{host}/v7/weather/now"
        params = {"location": location_id}
        headers = {"X-QW-Api-Key": key}

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        return "天气查询超时，请稍后重试。"
    except requests.exceptions.RequestException as e:
        return f"天气查询失败：{e}"

    if data.get("code") != "200":
        return f"查询失败：{data.get('code')}"

    now = data["now"]
    return (
        f"{args.city}：{now['text']}，"
        f"温度 {now['temp']}℃，"
        f"体感 {now['feelsLike']}℃，"
        f"湿度 {now['humidity']}%"
    )


if __name__ == "__main__":
    print("name:", get_weather.name)
    print("description:", get_weather.description)
    print("args_schema:", get_weather.args_schema.model_json_schema())
    print("\n调用结果：")
    print(get_weather.invoke({"city": "北京"}))
