import json

from pydantic import BaseModel, Field


class KeyPoint(BaseModel):
    point: str = Field(description="要点内容")
    importance: int = Field(description="重要性1-5")


class Source(BaseModel):
    url: str = Field(description="链接")
    title: str | None = Field(default=None, description="标题，可选")
    author: str = Field(default="未知", description="作者")


class StudyNote(BaseModel):
    topic: str = Field(description="主题")
    summary: str = Field(description="摘要")
    key_points: list[KeyPoint] = Field(description="关键点列表")
    sources: list[Source] = Field(description="引用来源列表")


note = StudyNote(
    topic="Python asyncio",
    summary="asyncio 是 Python 的异步 IO 框架",
    key_points=[
        KeyPoint(point="基于事件循环", importance=5),
        KeyPoint(point="适合 IO 密集型任务", importance=4),
    ],
    sources=[
        Source(url="https://docs.python.org/3/library/asyncio.html", title="官方文档"),
        Source(url="https://example.com"),
    ],
)
print(note)
print("\n=== JSON Schema ===")


print(json.dumps(StudyNote.model_json_schema(), indent=2, ensure_ascii=False))
