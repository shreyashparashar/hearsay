"""Explains a finished simulation in human terms: one-line verdict, what happened when, how each
group moved and why, individual people's reactions, and how it compares with history."""
import json

import numpy as np

from .engine import BELIEVER, REJECTER, SPREADER, UNAWARE
from .interpret import chat, llm_config, parse_json


def _pct(x):
    return f"{x * 100:.1f}%" if x < 0.1 else f"{x * 100:.0f}%"


def _day(h):
    d = h / 24
    return f"day {d:.1f}" if d < 2 else f"day {d:.0f}"


def verdict(k, spec):
    brand = spec.get("brand") or "the brand"
    d, reach = k["opinion_change"], k["reach"]
    if reach < 0.12:
        return "Barely noticed", f"Only {_pct(reach)} of people ever heard about it; most of the public moved on without forming a view."
    if k["polarization_change"] > 0.06 and spec["features"]["identity"] > 0.5:
        return "A split crowd", (f"Opinion about {brand} pulled apart: supporters warmed while opponents hardened, "
                                 f"and {_pct(k['hostile_end'])} of people ended up strongly against.")
    if d < -0.08 or k["churn"] > 0.05:
        return "A real backlash", (f"Attitude toward {brand} fell by {abs(d):.2f} on a −1 to +1 scale"
                                   + (f" and {_pct(k['churn'])} of existing customers walked away." if k["churn"] > 0.005 else "."))
    if d > 0.05:
        return "A clear win", (f"{_pct(reach)} of people heard about it and attitude toward {brand} rose by {d:.2f}"
                               + (f"; {_pct(k['adoption'])} of potential buyers acted." if k["adoption"] > 0.002 else "."))
    if k["peak_posts"] > 0 and k["negative_peak"] - k["negative_start"] > 0.03:
        return "Loud, then forgotten", (f"Negative feeling peaked on {_day(k['negative_peak_hour'])} but faded; "
                                        f"by the end attitude was within {abs(d):.2f} of where it started.")
    return "Noted, not moved", f"{_pct(reach)} of people heard about it, but attitudes barely changed ({d:+.2f})."


def segment_cards(q, sim, pop, spec):
    out = []
    final = sim.state
    S = len(pop.segment_names)
    seg_n = np.maximum(np.bincount(pop.segment, minlength=S), 1)
    for i, name in enumerate(pop.segment_names):
        mask = pop.segment == i
        believed = []
        for n in sim.narr:
            st = final[n.idx]
            b = ((st == SPREADER) | (st == BELIEVER)) & mask
            believed.append((b.sum() / seg_n[i], n))
        a0, a1 = q[f"opinion_{name}_p50"][0], q[f"opinion_{name}_p50"][-1]
        direction = np.sign(a1 - a0) or -1   # drivers = stories pushing the way this group actually moved
        believed.sort(key=lambda x: -x[0] * (max(0.0, direction * x[1].valence) + 0.05))
        note = next((s.get("note", "") for s in spec.get("audience", []) if s["name"] == name), "")
        out.append({
            "name": name, "share": float(mask.mean()), "opinion_start": float(a0), "opinion_end": float(a1),
            "aware": float(q[f"aware_seg_{name}_p50"][-1]),
            "adoption": float(q[f"adoption_{name}_p50"][-1]) if f"adoption_{name}_p50" in q else None,
            "churn": float(q[f"churn_{name}_p50"][-1]) if f"churn_{name}_p50" in q else None,
            "drivers": [{"label": n.label, "share": float(s), "valence": n.valence} for s, n in believed[:3] if s > 0.005],
            "curve": [float(x) for x in q[f"opinion_{name}_p50"][::4]], "note": note})
    return out


def _describe(pop, i):
    bits = []
    if pop.skepticism[i] > 0.6:
        bits.append("skeptical")
    elif pop.skepticism[i] < 0.2:
        bits.append("trusting")
    if pop.reactivity[i] > 0.7:
        bits.append("quick to react")
    if pop.expressiveness[i] > 0.3:
        bits.append("posts a lot")
    elif pop.expressiveness[i] < 0.05:
        bits.append("mostly scrolls")
    if pop.trust_brand[i] < 0.3:
        bits.append("distrusts the brand")
    elif pop.trust_brand[i] > 0.7:
        bits.append("trusts the brand")
    if abs(pop.ideology[i]) > 0.6:
        bits.append("strong cultural views")
    return ", ".join(bits) or "fairly average"


def voices(sim, pop, net, spec):
    """Pick real agents with telling trajectories and describe what happened to each."""
    rng = np.random.default_rng(3)
    o0, o1 = pop.opinion0, sim.opinion
    aware = sim.product_aware
    brand = spec.get("brand") or "them"
    picks = []

    def pick(mask, key=None, why=""):
        idx = np.flatnonzero(mask)
        if idx.size == 0:
            return
        i = int(idx[np.argmax(key[idx])]) if key is not None else int(rng.choice(idx))
        if i not in [p[0] for p in picks]:
            picks.append((i, why))

    false_stories = [n for n in sim.narr if n.truth is False]
    pick(aware, o0 - o1, "turned against")
    pick(aware, o1 - o0, "won over")
    if false_stories:
        st = sim.state[false_stories[0].idx]
        pick(st == SPREADER, pop.expressiveness, "spread the rumor")
        pick((st == REJECTER) & (pop.skepticism > 0.6), None, "saw through the rumor")
    pick(sim.churned, None, "left")
    pick(sim.adopted & (sim.adopt_time >= 0), None, "bought")
    infl = net.influencers[:20]
    pick(np.isin(np.arange(pop.n), infl) & aware, None, "big account")
    pick(~aware & (pop.activity < 0.2), None, "never heard")
    out = []
    for i, why in picks[:8]:
        stories = []
        for n in sim.narr:
            s = int(sim.state[n.idx, i])
            if s != UNAWARE:
                stories.append({"label": n.label, "status": ["", "shared it", "believed it", "rejected it"][s]})
        believed = [(n.valence, n.label) for n in sim.narr if int(sim.state[n.idx, i]) in (SPREADER, BELIEVER)]
        out.append({"agent": i, "segment": pop.segment_names[pop.segment[i]], "who": _describe(pop, i),
                    "followers": int(net.followers[i]), "opinion_start": float(o0[i]), "opinion_end": float(o1[i]),
                    "bought": bool(sim.adopted[i] and sim.adopt_time[i] >= 0), "left": bool(sim.churned[i]),
                    "why": why, "stories": stories, "quote": _template_quote(why, believed, stories, brand)})
    return out


def _template_quote(why, believed, stories, brand):
    worst = min(believed)[1] if believed else (stories[0]["label"] if stories else "all this")
    best = max(believed)[1] if believed else (stories[0]["label"] if stories else "all this")
    return {
        "turned against": f"I used to be fine with {brand}. After {worst}, I'm out.",
        "won over": f"Didn't think much of {brand} before. Honestly, {best} changed my mind.",
        "spread the rumor": f"Sharing this so people know. Look into {worst} before you buy anything.",
        "saw through the rumor": "Saw the scary posts. Nobody has shown actual proof, so I'm not buying it.",
        "left": f"Cancelled. Not giving {brand} another cent after this week.",
        "bought": "Picked one up. We'll see if it lives up to the noise.",
        "big account": f"Everyone's asking what I think about {brand}. Here's my take.",
        "never heard": "Wait, what happened? I've been offline all week.",
    }.get(why, "No strong feelings.")


def _llm_voices(vs, spec):
    try:
        payload = [{"who": v["who"], "group": v["segment"], "what_happened_to_them": v["why"],
                    "stories_seen": v["stories"], "attitude_before": round(v["opinion_start"], 2),
                    "attitude_after": round(v["opinion_end"], 2), "bought": v["bought"], "left": v["left"]} for v in vs]
        raw = chat([{"role": "system", "content": "Write one realistic social-media post or remark (max 30 words) for "
                     "each simulated person, in their voice, consistent with what happened to them. No hashtags spam, "
                     "no slurs, no real names. Return JSON {\"quotes\": [..]} in the same order."},
                    {"role": "user", "content": f"Event: {spec.get('summary')}\nPeople: {json.dumps(payload)}"}])
        quotes = parse_json(raw).get("quotes", [])
        for v, qt in zip(vs, quotes):
            if isinstance(qt, str) and qt.strip():
                v["quote"] = qt.strip()[:240]
    except Exception:
        pass
    return vs


def briefing(spec, k, title, line, timeline, cards, analogs, patterns):
    if llm_config():
        try:
            facts = {"event": spec.get("summary"), "verdict": [title, line], "numbers": k,
                     "timeline": [f"{_day(e['hour'])}: {e['text']}" for e in timeline[:18]],
                     "groups": [{c["name"]: [round(c["opinion_start"], 2), round(c["opinion_end"], 2)]} for c in cards],
                     "historical_analogs": [f"{a['name']} ({a['year']}): {a['summary']}" for a in analogs[:3]],
                     "patterns": [p["title"] for p in patterns]}
            return chat([{"role": "system", "content": "You are a sharp communications strategist. From the simulation "
                          "facts, write a briefing of 130-180 words in three short paragraphs: what happened, why it "
                          "happened (name the stories and groups that drove it), and what to do or watch next. Plain "
                          "language, no headings, no bullet points, no hype. Say clearly that this is a simulation."},
                         {"role": "user", "content": json.dumps(facts)}], json_mode=False).strip()
        except Exception:
            pass
    top = sorted(cards, key=lambda c: abs(c["opinion_end"] - c["opinion_start"]), reverse=True)[0]
    drivers = ", ".join(d["label"] for d in top["drivers"][:2]) or "the main story"
    p1 = f"{title}. {line}"
    p2 = (f"The group that moved most was {top['name']} ({top['opinion_start']:+.2f} → {top['opinion_end']:+.2f}), "
          f"driven mostly by {drivers}.")
    a = analogs[0] if analogs else None
    p3 = (f"The closest past case is {a['name']} ({a['year']}): {a['lessons'][0] if a.get('lessons') else a['summary']}"
          if a else "")
    if patterns:
        p3 += f" Pattern to watch: {patterns[0]['title'].lower()}."
    return "\n\n".join(x for x in (p1, p2, p3 + " This is a simulation, not a forecast.") if x)


def build(spec, cfg, extras, q, sim, pop, net, runs):
    hours = q["hour"]
    N = pop.n
    k = {
        "reach": float(q["product_awareness_p50"][-1]),
        "opinion_start": float(q["mean_opinion_p50"][0]), "opinion_end": float(q["mean_opinion_p50"][-1]),
        "negative_start": float(q["negative_share_p50"][0]), "negative_peak": float(q["negative_share_p50"].max()),
        "negative_peak_hour": int(hours[np.argmax(q["negative_share_p50"])]),
        "hostile_end": float(q["hostile_share_p50"][-1]),
        "peak_posts": float(q["posts_total_p50"].max()), "peak_posts_hour": int(hours[np.argmax(q["posts_total_p50"])]),
        "adoption": float(q["adoption_p50"][-1]), "adoption_lo": float(q["adoption_p10"][-1]),
        "adoption_hi": float(q["adoption_p90"][-1]),
        "churn": float(q["churn_p50"][-1]), "churn_lo": float(q["churn_p10"][-1]), "churn_hi": float(q["churn_p90"][-1]),
        "polarization_change": float(q["polarization_p50"][-1] - q["polarization_p50"][0]),
        "incidents": int(q["incidents_p50"][-1]),
    }
    k["opinion_change"] = k["opinion_end"] - k["opinion_start"]
    title, line = verdict(k, spec)

    seen, timeline = set(), []
    for e in sim.events:
        key = (e["kind"], e.get("story"), e["text"])
        if key in seen:
            continue
        seen.add(key)
        timeline.append(e)
    timeline.append({"hour": k["peak_posts_hour"], "kind": "peak", "text": "Conversation peaks.", "story": None})
    if k["negative_peak"] - k["negative_start"] > 0.01:
        timeline.append({"hour": k["negative_peak_hour"], "kind": "peak",
                         "text": f"Negative feeling peaks at {_pct(k['negative_peak'])} of people.", "story": None})
    timeline.sort(key=lambda e: e["hour"])

    cards = segment_cards(q, sim, pop, spec)
    vs = voices(sim, pop, net, spec)
    if llm_config():
        vs = _llm_voices(vs, spec)

    stories = []
    for n in sim.narr:
        stories.append({"id": n.id, "label": n.label, "kind": n.kind, "valence": n.valence, "truth": n.truth,
                        "start": n.start, "description": n.description, "picked_up": n.picked_up_at,
                        "aware": [float(x) for x in q[f"aware_{n.id}_p50"][::2]],
                        "posts": [float(x) for x in q[f"posts_{n.id}_p50"][::2]],
                        "aware_end": float(q[f"aware_{n.id}_p50"][-1]),
                        "believe_end": float(q[f"believe_{n.id}_p50"][-1])})

    pri = extras["priors"]
    sim_halflife = None
    pt = np.convolve(q["posts_total_p50"], np.ones(12) / 12, mode="same")   # smooth hourly noise
    if pt.max() > 0:
        pk = int(np.argmax(pt))
        after = np.flatnonzero(pt[pk:] < pt[pk] / 2)
        sim_halflife = float(after[0] / 24) if after.size else None
    history = {"expected": pri, "simulated": {"opinion_shift": k["opinion_change"], "awareness": k["reach"],
                                              "halflife_days": sim_halflife}}

    snap = sim.snap
    crowd = None
    if snap:
        import base64
        crowd = {"n": int(snap["idx"].size), "hours": snap["hours"],
                 "segment": base64.b64encode(pop.segment[snap["idx"]].astype(np.uint8).tobytes()).decode(),
                 "opinion": base64.b64encode(np.stack(snap["opinion"]).tobytes()).decode(),
                 "flags": base64.b64encode(np.stack(snap["flags"]).tobytes()).decode()}

    series = {"hours": [int(h) for h in hours[::2]]}
    for key in ("mean_opinion", "adoption", "churn", "negative_share", "positive_share"):
        for p in (10, 50, 90):
            series[f"{key}_p{p}"] = [float(x) for x in q[f"{key}_p{p}"][::2]]
    for key in ("posts_total", "buzz", "attention", "net_sentiment_posts", "hostile_share", "polarization",
                "product_awareness"):
        series[key] = [float(x) for x in q[f"{key}_p50"][::2]]

    return {
        "verdict": {"title": title, "line": line},
        "briefing": briefing(spec, k, title, line, timeline, cards, extras["analogs"], extras["patterns"]),
        "kpis": k, "timeline": timeline, "segments": cards, "voices": vs, "stories": stories, "series": series,
        "history": history, "analogs": extras["analogs"], "patterns": extras["patterns"], "crowd": crowd,
        "meta": {"agents": N, "ties": int(net.n_edges), "hours": int(len(hours)), "runs": runs,
                 "segments": pop.segment_names, "top_followers": int(net.followers.max())},
    }
