"""Runs simulations as background jobs (one at a time: they're CPU-bound) and keeps results."""
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from . import narrate
from .composer import compose
from .engine import Simulation
from .network import build_network
from .population import Population
from .report import quantiles

_pool = ThreadPoolExecutor(max_workers=1)
_jobs = {}
_lock = threading.Lock()


def get(job_id):
    with _lock:
        j = _jobs.get(job_id)
        return dict(j) if j else None


def _set(job_id, **kw):
    with _lock:
        _jobs[job_id].update(kw)


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
                         "created": time.time(), "result": None, "error": None,
                         "plan": extras["plan"], "agents": cfg["population"]["size"]}
    _pool.submit(_run, job_id, spec, cfg, extras)
    return job_id


def run_sync(spec, settings, progress=None):
    """Same pipeline without the queue (CLI, tests)."""
    cfg, extras = compose(spec, settings)
    return _simulate(spec, cfg, extras, progress or (lambda *a: None))


def _run(job_id, spec, cfg, extras):
    try:
        _set(job_id, status="running", message="Building the population")
        result = _simulate(spec, cfg, extras, lambda p, m: _set(job_id, progress=p, message=m))
        _set(job_id, status="done", progress=1.0, message="Done", result=result)
    except Exception as e:
        traceback.print_exc()
        _set(job_id, status="error", error=f"{type(e).__name__}: {e}", message="The simulation failed")


def _simulate(spec, cfg, extras, progress):
    t0 = time.time()
    seed = int(cfg["simulation"]["seed"])
    rng = np.random.default_rng(seed)
    pop = Population(cfg, rng)
    net = build_network(pop, cfg, rng)
    progress(0.04, f"Wired {pop.n:,} people with {net.n_edges:,} ties")
    runs = extras["runs"]
    hours = int(cfg["simulation"]["hours"])
    histories, first = [], None
    for r in range(runs):
        sim = Simulation(cfg, pop, net, seed + 1000 + r, snapshot_agents=4096 if r == 0 else 0, snapshot_every=6)
        for t in range(hours):
            sim.step()
            if t % 6 == 0:
                done = (r * hours + t + 1) / (runs * hours)
                progress(0.05 + 0.9 * done, f"Run {r + 1} of {runs}: day {t // 24 + 1} of {hours // 24}")
        histories.append(sim.history_arrays())
        if first is None:
            first = sim
    progress(0.96, "Writing up what happened")
    q = quantiles(histories)
    result = narrate.build(spec, cfg, extras, q, first, pop, net, runs)
    result["plan"] = extras["plan"]
    result["meta"]["seconds"] = round(time.time() - t0, 1)
    result["meta"]["archetype"] = extras["archetype_label"]
    return result
