"""The memory of past public reactions: find analogs for a new event, the patterns that apply,
and the priors (how long attention lasted, how opinion and sales moved) they imply."""
import json
import math
import os
from functools import lru_cache

import yaml

HERE = os.path.join(os.path.dirname(__file__), "knowledge")
FEATURES = ["valence", "emotionality", "identity", "lean", "harm", "responsibility",
            "hype", "price", "prominence", "novelty"]
WEIGHTS = {"valence": 1.2, "emotionality": 1.0, "identity": 1.5, "lean": 0.6, "harm": 1.5,
           "responsibility": 0.8, "hype": 0.8, "price": 0.8, "prominence": 0.5, "novelty": 0.5}
RELATED = [{"safety_defect", "disaster", "outage"}, {"values_controversy", "ad_misfire", "rebrand"},
           {"data_breach", "trust_scandal"}, {"product_launch", "viral_fad"},
           {"price_change", "rebrand"}, {"service_incident", "outage"}, {"financial_panic", "viral_fad"},
           {"government_policy", "price_change", "political_moment"},
           {"geopolitical_crisis", "values_controversy", "political_moment"},
           {"economic_shock", "financial_panic", "price_change"}, {"public_health", "safety_defect", "government_policy"},
           {"labor_dispute", "trust_scandal", "service_incident"}, {"geopolitical_crisis", "economic_shock", "disaster"}]


@lru_cache(maxsize=1)
def library():
    with open(os.path.join(HERE, "events.yaml")) as f:
        events = yaml.safe_load(f)["events"]
    learned_path = os.path.join(HERE, "attention_learned.json")
    learned = {}
    if os.path.exists(learned_path):
        with open(learned_path) as f:
            learned = json.load(f)
    for e in events:
        e.setdefault("domain", "brand")
        e.setdefault("country", "")
        if e["id"] in learned:   # real Wikipedia-pageview attention beats the hand-coded guess
            m = learned[e["id"]]
            e["outcome"]["halflife_days"] = m["halflife_days"]
            e["outcome"]["peak_day"] = m["peak_day"]
            e["attention_curve"] = m.get("curve")
            e["attention_source"] = "wikipedia pageviews"
        else:
            e["attention_source"] = "coded estimate"
    with open(os.path.join(HERE, "archetypes.yaml")) as f:
        archetypes = yaml.safe_load(f)
    with open(os.path.join(HERE, "patterns.yaml")) as f:
        patterns = yaml.safe_load(f)["patterns"]
    return {"events": events, "archetypes": archetypes, "patterns": patterns,
            "by_id": {e["id"]: e for e in events}}


def _distance(f, g, a, b):
    d = 0.0
    for k in FEATURES:
        x, y = float(f.get(k, 0)), float(g.get(k, 0))
        w = WEIGHTS[k]
        if k == "lean":   # lean only matters when both events carry identity charge
            w *= min(float(f.get("identity", 0)), float(g.get("identity", 0)))
        d += w * (x - y) ** 2
    d = math.sqrt(d)
    if a == b:
        d -= 0.45
    elif any(a in s and b in s for s in RELATED):
        d -= 0.2
    return max(d, 0.0)


def analogs(features, archetype, k=5):
    lib = library()
    scored = sorted(((_distance(features, e["features"], archetype, e["archetype"]), e) for e in lib["events"]),
                    key=lambda x: x[0])[:k]
    out = []
    for d, e in scored:
        out.append({"id": e["id"], "name": e["name"], "year": e["year"], "archetype": e["archetype"],
                    "domain": e.get("domain"), "country": e.get("country"),
                    "similarity": round(math.exp(-d * d / 1.2), 3), "summary": e["summary"],
                    "lessons": e.get("lessons", []), "outcome": e["outcome"],
                    "response": e.get("response", {}), "attention_source": e["attention_source"],
                    "attention_curve": e.get("attention_curve")})
    return out


def priors(found):
    """Similarity-weighted expectations from the closest historical events."""
    w = [a["similarity"] for a in found]
    tot = sum(w) or 1.0
    keys = ["awareness", "halflife_days", "peak_day", "opinion_shift", "commercial", "polarization"]
    return {k: round(sum(a["outcome"][k] * wi for a, wi in zip(found, w)) / tot, 3) for k in keys}


def _check(cond, value):
    if isinstance(cond, bool):
        return bool(value) == cond
    cond = str(cond)
    if cond.startswith("in:"):
        return str(value) in cond[3:].split(",")
    if value is None:
        return False
    for op in (">=", "<=", ">", "<"):
        if cond.startswith(op):
            x, y = float(value), float(cond[len(op):])
            return {">=": x >= y, "<=": x <= y, ">": x > y, "<": x < y}[op]
    return str(value) == cond


def matching_patterns(ctx):
    lib = library()
    out = []
    for p in lib["patterns"]:
        if all(_check(c, ctx.get(k)) for k, c in p["when"].items()):
            out.append({"id": p["id"], "title": p["title"], "text": p["text"],
                        "evidence": [{"id": i, "name": lib["by_id"][i]["name"], "year": lib["by_id"][i]["year"]}
                                     for i in p["evidence"] if i in lib["by_id"]],
                        "effects": p.get("effects") or {}})
    return out


def apply_effects(model, patterns):
    for p in patterns:
        for k, v in p["effects"].items():
            if isinstance(v, str) and v.startswith("*"):
                model[k] = model[k] * float(v[1:])
            else:
                model[k] = float(v)
    return model


def match_condition(cond, features):
    """`when` strings in archetype stories, e.g. "price>0.55"."""
    if not cond:
        return True
    for op in (">=", "<=", ">", "<"):
        if op in cond:
            k, v = cond.split(op, 1)
            return _check(op + v, features.get(k.strip(), 0))
    return True
