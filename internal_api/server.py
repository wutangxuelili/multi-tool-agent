"""公司内部 API 服务。

模拟一个内部系统，提供公告查询接口。
运行方式：uvicorn internal_api.server:app --port 8001
"""

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

app = FastAPI(title="Company Internal API", version="0.1.0")

# ---------- 模拟数据 ----------
ANNOUNCEMENTS = [
    {
        "id": 1,
        "title": "年会通知",
        "content": "公司年会将于 2026 年 1 月 20 日在国际会议中心举行，请各部门提前准备节目。",
        "date": "2026-01-01",
        "category": "活动",
    },
    {
        "id": 2,
        "title": "系统维护",
        "content": "本周六凌晨 2:00-4:00 进行服务器维护，期间内部系统暂停服务。",
        "date": "2026-01-05",
        "category": "运维",
    },
    {
        "id": 3,
        "title": "新员工培训",
        "content": "1 月 15 日上午 9:00 在 3 楼会议室开展新员工入职培训。",
        "date": "2026-01-08",
        "category": "培训",
    },
    {
        "id": 4,
        "title": "报销流程更新",
        "content": "从 2026 年 2 月起，报销单需附电子发票原件，纸质发票不再接受。",
        "date": "2026-01-10",
        "category": "财务",
    },
]


# ---------- 数据模型 ----------
class Announcement(BaseModel):
    id: int
    title: str
    content: str
    date: str
    category: str


class AnnouncementList(BaseModel):
    total: int
    announcements: list[Announcement]


# ---------- 接口 ----------
@app.get("/health")
def health():
    """健康检查。"""
    return {"status": "ok"}


@app.get("/announcements", response_model=AnnouncementList)
def list_announcements(
    limit: int = Query(default=5, ge=1, le=20, description="最多返回几条，范围 1-20"),
    category: str | None = Query(default=None, description="可选，按分类过滤"),
):
    """列出公告。

    :param limit: 最多返回几条，默认 5（超出 1-20 会被 FastAPI 直接拒绝为 422）
    :param category: 可选，按分类过滤
    """
    results = ANNOUNCEMENTS
    if category:
        results = [a for a in results if a["category"] == category]
    results = results[:limit]
    return {"total": len(results), "announcements": results}


@app.get("/announcements/{announcement_id}", response_model=Announcement)
def get_announcement(announcement_id: int):
    """按 ID 获取单条公告。"""
    for a in ANNOUNCEMENTS:
        if a["id"] == announcement_id:
            return a
    raise HTTPException(
        status_code=404, detail=f"未找到 ID 为 {announcement_id} 的公告"
    )
