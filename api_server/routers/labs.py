
from fastapi import APIRouter
router = APIRouter()

@router.post("")
def run_lab(task: dict):
    return {"status": "queued", "task": task}
