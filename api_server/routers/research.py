
from fastapi import APIRouter
router = APIRouter()

@router.post("")
def run_research(topic: dict):
    return {"status": "queued", "topic": topic}
