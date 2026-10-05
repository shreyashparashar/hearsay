"""Turns an event spec (from the model or the user's edits) plus the dashboard settings into a full
scenario: who the public is, which stories will circulate and when, how the organisation responds,
what else is going on in the world, and behavioural constants nudged by history."""
import copy
import os

from .engine import DEFAULT_MODEL
from .knowledge import analogs, apply_effects, library, match_condition, matching_patterns, priors

MAX_AGENTS = int(os.getenv("CROWDSIM_MAX_AGENTS", "1000000"))

RESPONSES = {
    "apology": dict(label="the apology", kind="response", valence=0.35, credibility=0.6, emotionality=0.4,
                    description="The organisation says sorry and owns the problem."),
    "denial": dict(label="the denial", kind="debunk", valence=0.3, credibility=0.55, emotionality=0.3,
                   description="The organisation says the claims are false."),
    "clarification": dict(label="the clarification", kind="debunk", valence=0.2, credibility=0.7, emotionality=0.2,
                          description="The organisation lays out the facts with evidence."),
    "recall": dict(label="the recall / fix", kind="response", valence=0.45, credibility=0.8, emotionality=0.45,
                   description="Products are recalled or fixed; new incidents stop."),
    "compensation": dict(label="the compensation offer", kind="response", valence=0.4, credibility=0.75,
                         emotionality=0.4, description="Affected people are offered refunds or credit."),
    "reversal": dict(label="the reversal", kind="response", valence=0.5, credibility=0.8, emotionality=0.5,
                     description="The organisation walks the change back."),
    "stand_firm": dict(label="standing firm", kind="response", valence=0.15, credibility=0.7, emotionality=0.5,
                       description="The organisation stands by its decision."),
    "humor": dict(label="the joke response", kind="response", valence=0.3, credibility=0.6, emotionality=0.7,
                  description="The organisation answers with self-aware humour."),
}
NEWS_LOAD = {"quiet": 1.0, "normal": 0.85, "busy": 0.65, "saturated": 0.45}
POLARIZATION = {"low": 0.2, "medium": 0.45, "high": 0.75}
ECONOMY = {"boom": (-0.1, 1.25, 0.8), "normal": (0.0, 1.0, 1.0), "downturn": (0.15, 0.7, 1.3)}


def _side(target, lean):
    if target not in ("lean_same", "lean_opposite"):
        return target
    if abs(lean) < 0.15:
        return "active"
    plus = (lean > 0) == (target == "lean_same")
    return "lean_plus" if plus else "lean_minus"


def _story(t, f, q, origin):
    d = copy.deepcopy(t)
    if d.get("valence") == "quality":
        d["valence"] = q
    if d.get("identity") == "same":
        d["identity"] = f["identity"]
    if d.get("lean") == "same":
        d["lean"] = f["lean"]
    elif d.get("lean") == "opposite":
        d["lean"] = -f["lean"]
    if d.get("seed"):
        d["seed"]["target"] = _side(d["seed"].get("target", "active"), f["lean"])
    d.pop("when", None)
    d["origin"] = origin
    return d


def compose(spec, settings):
    lib = library()
    arche = lib["archetypes"][spec["archetype"]]
    f = dict(spec["features"])
    q = float(spec.get("quality", 0.0))
    agents = int(min(max(int(settings.get("agents", 200_000)), 10_000), MAX_AGENTS))
    days = int(min(max(int(settings.get("days", 10)), 2), 30))
    hours = days * 24
    resp = settings.get("response") or {}
    rtype = resp.get("type", "none")
    rhour = int(resp.get("hour", 24)) if rtype != "none" else None
    econ = ECONOMY.get(settings.get("economy", "normal"), ECONOMY["normal"])

    # ---- who the public is
    src = spec.get("audience") or [
        {**g, "already_customer": g.get("already_adopted", 0.0)} for g in arche["audience"]]
    segments = []
    for g in src:
        seg = {"name": g["name"], "share": float(g["share"]),
               "baseline_opinion": float(g.get("baseline_opinion", 0)), "opinion_sd": 0.25,
               "can_adopt": bool(g.get("can_adopt", False)),
               "already_adopted": float(g.get("already_customer", g.get("already_adopted", 0.0))),
               "need": float(g.get("need", 0.5)),
               "price_sensitivity": min(1, max(0, float(g.get("price_sensitivity", 0.5)) + econ[0])),
               "ideology": float(g.get("ideology", 0.0)), "note": g.get("note", "")}
        if g.get("traits"):
            seg["traits"] = g["traits"]
        if g.get("activity"):
            seg["activity"] = g["activity"]
        segments.append(seg)
    if not any(not s["can_adopt"] and "public" in s["name"].lower() for s in segments):
        segments.append({"name": "general public", "share": 0.5, "baseline_opinion": 0.0, "can_adopt": False,
                         "note": "Won't buy, but talks, judges and shares."})
    tot = sum(s["share"] for s in segments)
    for s in segments:
        s["share"] = s["share"] / tot
    if settings.get("global"):
        for i, s in enumerate(segments):
            s["tz_offset"] = [0, -5, 6, 9, -8][i % 5]

    # ---- history: analogs, priors, patterns
    found = analogs(f, spec["archetype"])
    prior = priors(found)
    ctx = {**f, "archetype": spec["archetype"], "response": rtype, "response_hour": rhour if rhour is not None else 10**6,
           "substitutes": spec.get("substitutes", 0.5), "crisis": bool(arche.get("crisis"))}
    pats = matching_patterns(ctx)

    model = {**DEFAULT_MODEL, **arche.get("dynamics", {})}
    hist_halflife = min(max(prior["halflife_days"] * 24 * 0.5, 8), 200)
    model["novelty_halflife"] = 0.5 * model["novelty_halflife"] + 0.5 * hist_halflife
    model = apply_effects(model, pats)
    model["adopt_base_rate"] *= econ[1] * (1.4 if settings.get("season") == "holiday" else 1.0)
    model["churn_rate"] *= econ[2]
    if spec["archetype"] == "safety_defect" or f["harm"] > 0.5:
        model["defect_rate"] = max(model["defect_rate"], 0.004 + 0.02 * f["harm"])

    # ---- the stories
    prom = f["prominence"]
    core_kind = arche["core_kind"]
    narratives = [{
        "id": "the_event", "kind": core_kind,
        "label": spec["title"] if 0 < len(spec.get("title") or "") <= 40 else
        {"official": "the announcement", "news": "the news", "ugc": "the viral post", "rumor": "the first warnings"}[core_kind],
        "source": {"official": "brand", "news": "media"}.get(core_kind, "none"),
        "valence": f["valence"], "credibility": f["credibility"], "emotionality": f["emotionality"],
        "identity": f["identity"], "lean": f["lean"], "start": 0,
        "seed": {"target": "influencers" if core_kind == "official" else "active",
                 "share": 0.0002 * (0.5 + prom) if core_kind == "official" else 0.0004},
        "media": [{"start": 0 if core_kind != "ugc" else 6, "end": int(12 + 24 * prom),
                   "intensity": round(0.02 + 0.08 * prom, 3)}],
        "description": spec.get("summary", ""), "origin": "your input"}]
    if core_kind in ("ugc", "rumor"):
        narratives[0]["media_pickup"] = {"threshold": 0.01, "delay": 3, "duration": 36, "intensity": 0.05}
        narratives[0]["media"] = []
    for t in arche.get("stories", []):
        if match_condition(t.get("when"), f) and t["start"] < hours:
            narratives.append(_story(t, f, q, "history"))
    have = {n["id"] for n in narratives}
    for st in spec.get("stories", []):
        if st["id"] in have or st["start_hour"] >= hours:
            continue
        have.add(st["id"])
        seed_target = "active"
        if st["kind"] == "movement" and st["identity"] > 0.3:
            seed_target = "lean_plus" if st["lean"] > 0 else "lean_minus"
        d = {"id": st["id"], "label": st["label"], "kind": st["kind"], "valence": st["valence"],
             "credibility": st["credibility"], "emotionality": st["emotionality"], "identity": st["identity"],
             "lean": st["lean"], "start": st["start_hour"], "truth": st["truth"],
             "seed": {"target": seed_target, "share": 0.0003}, "description": st["description"], "origin": "model"}
        if st["kind"] == "news":
            d["media"] = [{"start": st["start_hour"], "end": st["start_hour"] + 24, "intensity": 0.03}]
        if st["kind"] in ("rumor", "movement", "ugc"):
            d["media_pickup"] = {"threshold": 0.015, "delay": 3, "duration": 30, "intensity": 0.035}
        narratives.append(d)
    off = set(settings.get("disabled_stories") or [])
    moved = settings.get("story_hours") or {}
    narratives = [n for n in narratives if n["id"] == "the_event" or n["id"] not in off]
    for n in narratives:
        if n["id"] in moved and n["id"] != "the_event":
            n["start"] = int(min(max(int(moved[n["id"]]), 0), hours - 1))
            for m in n.get("media", []):
                m["end"] = n["start"] + (m["end"] - m["start"])
                m["start"] = n["start"]
    narratives = narratives[:9]   # keeps an hour of simulated time cheap

    # ---- the organisation's response
    if rtype in RESPONSES and rhour < hours:
        r = {**RESPONSES[rtype], "id": "your_response", "start": rhour, "source": "brand", "origin": "your plan",
             "seed": {"target": "influencers", "share": 0.0001 * (0.5 + prom)},
             "media": [{"start": rhour, "end": rhour + 24, "intensity": round(0.03 + 0.04 * prom, 3)}]}
        if rtype == "stand_firm":
            r.update(identity=f["identity"], lean=f["lean"])
        if rtype == "reversal" and f["identity"] > 0.4:
            r.update(identity=f["identity"], lean=-f["lean"])   # walking back angers the side that liked it
        if rtype == "humor" and f["harm"] > 0.5:
            r.update(valence=-0.3, description="A joke next to real harm reads as not taking it seriously.")
        if rtype in ("denial", "clarification"):
            false = [n for n in narratives if n.get("truth") is False]
            if false:
                r["debunks"] = false[0]["id"]
            elif arche.get("crisis"):
                r["debunks"] = "the_event"
                r["credibility"] *= 0.6   # denying something people can see is true
        if rtype == "recall":
            model["defect_stop_hour"] = rhour
        narratives.append(r)
    if arche.get("crisis") and (rhour is None or rhour > 48) and 36 < hours:
        narratives.append({"id": "company_silence", "label": "the organisation's silence", "kind": "news",
                           "valence": -0.4, "credibility": 0.7, "emotionality": 0.6, "start": 36,
                           "seed": {"target": "active", "share": 0.0002}, "origin": "history",
                           "description": '"Why haven\'t they said anything?"'})

    # ---- the world around it
    context = {"attention": NEWS_LOAD.get(settings.get("news_load", "normal"), 0.85),
               "polarization": POLARIZATION.get(settings.get("polarization", "medium"), 0.45),
               "attention_shocks": []}
    ce = settings.get("competing_event") or {}
    if ce.get("on"):
        h = int(ce.get("hour", 24))
        context["attention_shocks"].append({"start": h, "end": h + 48, "level": 0.5})

    cfg = {
        "name": spec.get("title", "event"),
        "simulation": {"hours": hours, "start_hour_of_day": int(settings.get("start_hour", 9)),
                       "seed": int(settings.get("seed", 42))},
        "population": {"size": agents, "segments": segments},
        "network": {"mean_degree": 12, "homophily": 0.8, "echo_chamber": 0.6},
        "context": context,
        "product": {"quality": q},
        "model": model,
        "narratives": narratives,
    }
    plan = [{"id": n["id"], "label": n.get("label", n["id"]), "kind": n.get("kind"), "start": n["start"],
             "valence": n.get("valence"), "truth": n.get("truth"), "origin": n.get("origin"),
             "description": n.get("description", ""), "debunks": n.get("debunks")} for n in narratives]
    return cfg, {"analogs": found, "priors": prior, "patterns": pats, "plan": plan,
                 "archetype_label": arche["label"], "runs": int(min(max(int(settings.get("runs", 2)), 1), 8))}
