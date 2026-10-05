"""Runs simulations as background jobs (one at a time: they're CPU-bound) and keeps results.

While the first run is going, a slice of the real network streams out hour by hour (who posted,
who heard it from whom, who believed it), so the page can show the conversation forming live.
"""
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import advisor, narrate
from .composer import compose
from .engine import Simulation
from .network import build_network
from .population import Population
from .report import quantiles
from .tracker import Tracker

_pool = ThreadPoolExecutor(max_workers=1)
_jobs = {}
_lock = threading.Lock()


def get(job_id, since=0):
    """A copy of the job without its bulky parts; network frames from `since` onwards."""
    with _lock:
        j = _jobs.get(job_id)
        if not j:
            return None
        out = {k: v for k, v in j.items() if k not in ("frames", "graph", "result")}
        frames = j["frames"]
        out["frames"] = frames[since:since + 96]
        out["frames_from"] = since
        out["frames_total"] = len(frames)
        if since == 0 and j.get("graph"):
            out["graph"] = j["graph"]
        if j["status"] == "done" and since + 96 >= len(frames):
            out["result"] = j["result"]
        return out


def _set(job_id, **kw):
    with _lock:
        _jobs[job_id].update(kw)


def _push_frame(job_id, frame):
    with _lock:
        _jobs[job_id]["frames"].append(frame)


def queue_position(job_id):
    with _lock:
        waiting = [k for k, v in _jobs.items() if v["status"] == "queued"]
    return waiting.index(job_id) + 1 if job_id in waiting else 0


def submit(spec, settings):
    job_id = uuid.uuid4().hex[:12]
    cfg, extras = compose(spec, settings)
    with _lock:
        # keep memory bounded: forget finished jobs older than an hour
        for k in [k for k, v in _jobs.items() if v["status"] in ("done", "error") and time.time() - v["created"] > 3600]:
            del _jobs[k]
        _jobs[job_id] = {"status": "queued", "progress": 0.0, "message": "Waiting for a free simulator",
                         "created": time.time(), "result": None, "error": None, "graph": None, "frames": [],
                         "lines": None, "lines_by": None,
                         "plan": extras["plan"], "agents": cfg["population"]["size"]}
    _pool.submit(_run, job_id, spec, settings, cfg, extras)
    return job_id


def run_sync(spec, settings, progress=None):
    """Same pipeline without the queue (CLI, tests)."""
    cfg, extras = compose(spec, settings)
    return _simulate(spec, settings, cfg, extras, progress or (lambda *a: None))


def _run(job_id, spec, settings, cfg, extras):
    try:
        _set(job_id, status="running", message="Building the population")
        hooks = {"graph": lambda g: _set(job_id, graph=g), "frame": lambda f: _push_frame(job_id, f),
                 "lines": lambda lines, by: _set(job_id, lines=lines, lines_by=by)}
        result = _simulate(spec, settings, cfg, extras, lambda p, m: _set(job_id, progress=p, message=m), hooks)
        _set(job_id, status="done", progress=1.0, message="Done", result=result)
    except Exception as e:
        traceback.print_exc()
        _set(job_id, status="error", error=f"{type(e).__name__}: {e}", message="The simulation failed")


def _simulate(spec, settings, cfg, extras, progress, hooks=None):
    hooks = hooks or {}
    t0 = time.time()
    seed = int(cfg["simulation"]["seed"])
    rng = np.random.default_rng(seed)

    # what people would actually type when they share each story (model in the background)
    lines_box = {}

    def make_lines():
        lines, by = narrate.story_lines(cfg["narratives"] + _engine_extra(cfg), spec)
        lines_box.update(lines=lines, by=by)
        if hooks.get("lines"):
            hooks["lines"](lines, by)
    tl = threading.Thread(target=make_lines, daemon=True)
    tl.start()

    pop = Population(cfg, rng)
    net = build_network(pop, cfg, rng)
    progress(0.03, f"Wired {pop.n:,} people with {net.n_edges:,} ties")
    runs = extras["runs"]
    hours = int(cfg["simulation"]["hours"])
    test = settings.get("test_options", True)
    share_main = 0.78 if test else 0.92
    histories, first, tracker = [], None, None
    for r in range(runs):
        sim = Simulation(cfg, pop, net, seed + 1000 + r)
        if r == 0:
            tracker = Tracker(pop, net, sim.narr, np.random.default_rng(seed + 5), on_frame=hooks.get("frame"))
            sim.tracker = tracker
            if hooks.get("graph"):
                hooks["graph"](tracker.graph(narrate._describe))
        for t in range(hours):
            sim.step()
            if t % 3 == 0:
                done = (r * hours + t + 1) / (runs * hours)
                progress(0.04 + share_main * done, f"Run {r + 1} of {runs}: day {t // 24 + 1} of {hours // 24}")
        histories.append(sim.history_arrays())
        if first is None:
            first = sim

    tested = None
    if test:
        base = 0.04 + share_main
        tested = advisor.test_options(spec, settings,
                                      lambda p, m: progress(base + (0.95 - base) * p, m))
    progress(0.96, "Writing up what happened")
    tl.join(timeout=40)
    q = quantiles(histories)
    network = None
    if tracker:
        network = {"graph": tracker.graph(narrate._describe), "frames": tracker.frames,
                   "lines": lines_box.get("lines") or narrate.story_lines(cfg["narratives"] + _engine_extra(cfg), spec, use_model=False)[0],
                   "lines_by": lines_box.get("by", "template")}
    result = narrate.build(spec, cfg, extras, q, first, pop, net, runs, tested=tested, network=network)
    result["plan"] = extras["plan"]
    result["meta"]["seconds"] = round(time.time() - t0, 1)
    result["meta"]["archetype"] = extras["archetype_label"]
    return result


def _engine_extra(cfg):
    """Stories the engine adds by itself (buyer reviews, incident posts) so they get lines too."""
    out = []
    ids = {n["id"] for n in cfg["narratives"]}
    q = (cfg.get("product") or {}).get("quality")
    if q is not None and "user_reviews" not in ids:
        out.append({"id": "user_reviews", "label": "buyer reviews", "valence": float(q),
                    "description": "Posts from people who bought and used it."})
    if (cfg.get("model") or {}).get("defect_rate", 0) > 0 and "user_incidents" not in ids:
        out.append({"id": "user_incidents", "label": "buyer incident posts", "valence": -0.7,
                    "description": "Photos and videos from buyers whose product failed them."})
    return out
