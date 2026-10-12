import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, field_validator

load_dotenv()


class WeatherReport(BaseModel):
    city: str = Field(description="城市名")
    weather: str = Field(description="天气状况")
    temperature: int = Field(description="温度，摄氏度")
    action: str = Field(description="建议用户做的事")

    @field_validator("temperature", mode="before")
    @classmethod
    def parse_temperature(cls, v):
        if isinstance(v, str):
            cleaned = "".join(c for c in v if c.isdigit() or c == "-")
            return int(cleaned)
        return v


llm = ChatOpenAI(
    base_url=os.getenv("LLM_BASE_URL"),
    api_key=os.getenv("LLM_API_KEY"),
    model="deepseek-chat",
)

structured_llm = llm.with_structured_output(WeatherReport, method="json_mode")

messages = [
    SystemMessage(
        content="请以 JSON 格式输出，包含 city, weather, temperature, action 字段。temperature 必须是数字，不带单位。"
    ),
    HumanMessage(content="北京今天多云，25℃，建议涂防晒"),
]

result = structured_llm.invoke(messages)
print(type(result))
print(result)
print(f"温度: {result.temperature}，类型: {type(result.temperature)}")
