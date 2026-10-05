"""Web dashboard + API.  Run:  uvicorn crowdsim.server:app --host 0.0.0.0 --port 7860"""
import os

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import advisor, service
from .composer import MAX_AGENTS, compose
from .interpret import interpret, llm_config, normalise
from .knowledge import library

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
MAX_IMAGES, MAX_IMAGE_BYTES = 4, 6 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

app = FastAPI(title="crowdsim", docs_url="/api/docs")


@app.get("/api/health")
def health():
    cfg = llm_config()
    return {"ok": True, "model": cfg["model"] if cfg else None, "vision_model": cfg["vision_model"] if cfg else None,
            "max_agents": MAX_AGENTS, "events_in_memory": len(library()["events"]),
            "option_agents": advisor.OPTION_AGENTS}


@app.get("/api/library")
def lib():
    L = library()
    return {"events": [{k: e.get(k) for k in ("id", "name", "year", "archetype", "summary", "lessons", "outcome",
                                                "features", "response", "attention_source", "domain", "country")}
                       for e in L["events"]],
            "domains": sorted({e.get("domain", "brand") for e in L["events"]}),
            "archetypes": {k: v["label"] for k, v in L["archetypes"].items()},
            "patterns": L["patterns"]}


@app.post("/api/read")
async def read(text: str = Form(""), context: str = Form(""), images: list[UploadFile] = File(default=[])):
    if not text.strip() and not images:
        raise HTTPException(400, "Describe what happened or add at least one image.")
    if len(text) > 8000:
        raise HTTPException(400, "Keep the description under 8,000 characters.")
    imgs = []
    for f in images[:MAX_IMAGES]:
        if f.content_type not in IMAGE_TYPES:
            raise HTTPException(400, f"{f.filename}: use PNG, JPEG, WebP or GIF.")
        data = await f.read()
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(400, f"{f.filename} is larger than 6 MB.")
        imgs.append((data, f.content_type))
    spec = interpret(text, imgs, context)
    return {"spec": spec, "archetypes": {k: v["label"] for k, v in library()["archetypes"].items()}}


class SimRequest(BaseModel):
    spec: dict
    settings: dict = {}


@app.post("/api/preview")
def preview(req: SimRequest):
    spec = normalise(req.spec)
    cfg, extras = compose(spec, req.settings)
    return {"plan": extras["plan"], "analogs": extras["analogs"], "priors": extras["priors"],
            "patterns": extras["patterns"], "segments": cfg["population"]["segments"],
            "archetype_label": extras["archetype_label"]}


@app.post("/api/simulate")
def simulate(req: SimRequest):
    spec = normalise(req.spec)
    spec["reader"] = req.spec.get("reader", "")
    return {"job": service.submit(spec, req.settings)}


@app.get("/api/jobs/{job_id}")
def job(job_id: str, since: int = 0):
    j = service.get(job_id, max(0, since))
    if not j:
        raise HTTPException(404, "That simulation no longer exists. Run it again.")
    j["queue_position"] = service.queue_position(job_id)
    return JSONResponse(j)


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/", StaticFiles(directory=WEB), name="web")
