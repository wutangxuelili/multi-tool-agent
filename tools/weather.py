import os

import requests
from dotenv import load_dotenv
from langchain_core.tools import tool
from pydantic import BaseModel, Field

load_dotenv()

REQUEST_TIMEOUT = 10  # 秒


class WeatherArgs(BaseModel):
    city: str = Field(min_length=1, description="城市名称，例如：北京")


def _api_config() -> tuple[str | None, str | None]:
    """读取和风天气配置（调用时读取，改 .env 后无需重启进程）。"""
    return os.getenv("HEFENG_API_HOST"), os.getenv("HEFENG_API_KEY")


def _lookup_location_id(city: str, host: str, key: str) -> str | None:
    """用城市名查询 LocationID。"""
    url = f"https://{host}/geo/v2/city/lookup"
    headers = {"X-QW-Api-Key": key}

    response = requests.get(
        url, params={"location": city}, headers=headers, timeout=REQUEST_TIMEOUT
    )
    response.raise_for_status()
    data = response.json()

    if data.get("code") != "200":
        return None
    locations = data.get("location") or []
    if not locations:
        return None
    # 接口字段缺失时返回 None，而不是 KeyError 炸穿整张图
    return locations[0].get("id")


@tool(args_schema=WeatherArgs)
def get_weather(city: str) -> str:
    """查询指定城市的当前天气。"""
    try:
        args = WeatherArgs.model_validate({"city": city})
    except Exception as e:  # noqa: BLE001
        return f"参数错误：{e}"

    host, key = _api_config()
    if not host or not key:
        return (
            "错误：未配置天气接口（缺少 HEFENG_API_HOST / HEFENG_API_KEY）。"
            "请复制 .env.example 为 .env 并填写后重试。"
        )

    try:
        location_id = _lookup_location_id(args.city, host, key)
        if not location_id:
            return f"未找到城市：{args.city}"

        response = requests.get(
            f"https://{host}/v7/weather/now",
            params={"location": location_id},
            headers={"X-QW-Api-Key": key},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.Timeout:
        return "天气查询超时，请稍后重试。"
    except requests.exceptions.RequestException as e:
        return f"天气查询失败：{e}"
    except ValueError:
        return "天气查询失败：接口返回的不是合法 JSON。"

    if data.get("code") != "200":
        return f"查询失败：{data.get('code')}"

    now = data.get("now") or {}
    if not now:
        return f"查询失败：接口未返回实时数据（code={data.get('code')}）。"

    return (
        f"{args.city}：{now.get('text', '未知')}，"
        f"温度 {now.get('temp', '?')}℃，"
        f"体感 {now.get('feelsLike', '?')}℃，"
        f"湿度 {now.get('humidity', '?')}%"
    )


if __name__ == "__main__":
    print("name:", get_weather.name)
    print("description:", get_weather.description)
    print("args_schema:", get_weather.args_schema.model_json_schema())
    print("\n调用结果：")
    print(get_weather.invoke({"city": "北京"}))
