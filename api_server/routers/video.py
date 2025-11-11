
from fastapi import APIRouter
router = APIRouter()

@router.post("/veo")
def gen_video_veo(req: dict):
    return {"status": "queued", "provider": "veo", "req": req}

@router.post("/hailuo")
def gen_video_hailuo(req: dict):
    return {"status": "queued", "provider": "hailuo", "req": req}
