"""Turns a simulation into a decision a non-specialist can act on.

1. `candidates` lists realistic alternatives to the plan (respond faster, apologise, explain on day
   one, lower the price, pilot it first, tone down the values messaging, walk it back...), chosen
   from what the event is and what history says works for it.
2. `test_options` actually runs every alternative through the same simulated society (smaller
   crowd, one run, same random seed so the only difference is the plan) and measures the outcome.
3. `decide` makes the call: go ahead / go ahead with a change / change it first / don't, with the
   reasons in plain words.
"""
import copy
import os

import numpy as np

from .composer import compose
from .engine import Simulation
from .network import build_network
from .population import Population

OPTION_AGENTS = int(os.getenv("CROWDSIM_OPTION_AGENTS", "25000"))
OPTION_DAYS = int(os.getenv("CROWDSIM_OPTION_DAYS", "7"))

# how each kind of event talks about "taking it up" and "walking away"
WORDS_DEFAULT = {"subject": "it", "adopt": "bought it", "adopters": "potential buyers",
                 "churn": "walked away", "customers": "existing customers", "org": "the brand",
                 "mode": "decide"}


def words(arche, spec=None):
    w = {**WORDS_DEFAULT, **(arche.get("words") or {})}
    w["mode"] = arche.get("mode") or ("respond" if arche.get("crisis") else "decide")
    if spec and spec.get("brand"):
        w["org"] = spec["brand"]
    return w


def score(m):
    """One number for comparing plans: attitude, take-up and losses, from the organisation's side."""
    return (m["opinion_change"] + 0.6 * m["adoption"] - 1.5 * m["churn"]
            - 0.6 * max(m["hostile_change"], 0.0) - 0.3 * max(m["against_end"] - m["against_start"], 0.0))


def metrics(h):
    return {"opinion_change": float(h["mean_opinion"][-1] - h["mean_opinion"][0]),
            "adoption": float(h["adoption"][-1]), "churn": float(h["churn"][-1]),
            "hostile_change": float(h["hostile_share"][-1] - h["hostile_share"][0]),
            "against_start": float(h["negative_share"][0]), "against_end": float(h["negative_share"][-1]),
            "for_end": float(h["positive_share"][-1]), "reach": float(h["product_awareness"][-1]),
            "peak_negative": float(h["negative_share"].max())}


def _clip(x, lo=0.0, hi=1.0):
    return float(min(hi, max(lo, x)))


def _has_false_story(spec, arche, f):
    if any(s.get("truth") is False for s in spec.get("stories", [])):
        return True
    from .knowledge import match_condition
    return any(t.get("truth") is False and match_condition(t.get("when"), f) for t in arche.get("stories", []))


def candidates(spec, settings, arche_key, arche):
    f = spec["features"]
    plan = settings.get("response") or {}
    ptype, phour = plan.get("type", "none"), int(plan.get("hour", 24))
    crisis = bool(arche.get("crisis"))
    w = words(arche, spec)
    org = w["org"] if w["org"] != "the brand" else "you"
    false_story = _has_false_story(spec, arche, f)
    out = []

    def add(id_, label, why, response=None, spec_mod=None, model_mod=None, settings_mod=None):
        if any(o["id"] == id_ for o in out):
            return
        if response and response["type"] == ptype and abs(int(response["hour"]) - phour) <= 3:
            return
        out.append({"id": id_, "label": label, "why": why, "response": response,
                    "spec_mod": spec_mod or {}, "model_mod": model_mod or {}, "settings_mod": settings_mod or {}})

    if crisis:
        if ptype not in ("none",) and phour > 8:
            add("faster", f"Same response, but within 6 hours instead of {phour}",
                "The first day decides who tells the story.", {"type": ptype, "hour": 6})
        if f["harm"] > 0.4:
            t = "recall" if arche_key in ("safety_defect", "disaster", "public_health") else "compensation"
            add(t, "Fix it or recall it within 6 hours" if t == "recall" else "Compensate the people affected within 6 hours",
                "When people can be hurt, visible action beats words.", {"type": t, "hour": 6})
        external = arche_key in ("geopolitical_crisis", "economic_shock", "public_health")
        if external:
            add("brief", "Give clear, regular official updates from the first hours",
                "In big shared crises, a steady trusted voice crowds out rumours.", {"type": "clarification", "hour": 3})
        if arche_key == "geopolitical_crisis":
            add("firm", "Take a firm public stance early", "Publics rally behind leaders who look in control.",
                {"type": "stand_firm", "hour": 6})
        if f["responsibility"] > (0.7 if external else 0.45):
            add("apology", "Apologise and own it within 6 hours",
                "Owning a mistake early takes the 'cover-up' story off the table.", {"type": "apology", "hour": 6})
        if false_story:
            add("clarify", "Correct the false claims with evidence within 6 hours",
                "Rumours spread fastest before anyone answers them.", {"type": "clarification", "hour": 6})
        if f["identity"] > 0.5:
            add("firm", "Stand firm and say why", "Wavering on a values question can lose both sides.",
                {"type": "stand_firm", "hour": 6})
            add("walkback", "Walk it back within a day", "Reversals end the fight, but anger the side that liked it.",
                {"type": "reversal", "hour": 24})
        if arche_key in ("price_change", "government_policy", "economic_shock"):
            add("walkback", "Walk it back after two days if it goes badly",
                "A quick reversal has capped the damage in past price and policy rows.", {"type": "reversal", "hour": 48})
        if ptype != "none":
            add("silent", "Say nothing", "For comparison: what happens if you stay quiet.", {"type": "none", "hour": 0})
        else:
            add("apology", "Apologise and own it within 12 hours", "For comparison with staying silent.",
                {"type": "apology", "hour": 12})
    else:
        if false_story or f.get("credibility", 0.75) < 0.7 or arche_key in ("government_policy", "rebrand"):
            add("explain", "Explain it plainly on day one, with evidence",
                "A clear explainer gets ahead of the questions and the rumours.", {"type": "clarification", "hour": 4})
        if f["price"] > 0.45:
            add("price", "Lower the cost to people (smaller fine, fee or tax)" if arche_key == "government_policy"
                else "Make it cheaper or easier to afford",
                "Price complaints were one of the stories working against you.",
                spec_mod={"price": -0.25, "valence": 0.08}, model_mod={"a_bias": 0.35})
        if float(spec.get("quality", 0)) < 0.4 and arche_key in ("product_launch", "viral_fad", "rebrand"):
            add("quality", "Fix the weak spots before launch",
                "Buyers' reviews feed back into what everyone else hears.", spec_mod={"quality": 0.3, "valence": 0.05})
        if f["identity"] > 0.4:
            add("tone", "Tone down the values and political charge",
                "Identity-charged messages split people into camps.", spec_mod={"identity": "*0.5", "emotionality": -0.1})
        if arche_key in ("government_policy", "price_change", "rebrand") or f["harm"] > 0.3:
            add("pilot", "Start with a pilot or phase it in",
                "Smaller, gradual changes give critics less to rally around.",
                spec_mod={"harm": -0.4, "novelty": -0.4, "emotionality": -0.1, "responsibility": -0.15})
        if settings.get("news_load") in ("busy", "saturated"):
            add("timing", "Wait for a quieter news week", "More attention can help or hurt; this tests which.",
                settings_mod={"news_load": "quiet"})
        if f["hype"] < 0.3 and f["valence"] > 0.2 and arche_key in ("product_launch", "viral_fad", "rebrand"):
            add("buzz", "Build anticipation first (teasers, early access)",
                "Positive news that nobody hears does nothing.", spec_mod={"hype": 0.35, "prominence": 0.1})
        if ptype == "none" and f["valence"] < 0:
            add("acknowledge", "Acknowledge the concerns within 12 hours", "Saying you've heard the worries, early.",
                {"type": "apology", "hour": 12})
        if arche_key == "government_policy" and f["harm"] > 0.2:
            add("relief", "Pair it with visible help for those who pay",
                "A concrete offer to the people bearing the cost takes the edge off hardship stories.",
                {"type": "compensation", "hour": 0})
    return out[:5]


def _apply(spec, settings, opt, days):
    s = copy.deepcopy(spec)
    for k, d in opt.get("spec_mod", {}).items():   # numbers add, "*x" multiplies
        lo = -1 if k in ("valence", "lean", "quality") else 0
        cur = s.get("quality", 0) if k == "quality" else s["features"].get(k, 0)
        new = cur * float(d[1:]) if isinstance(d, str) else cur + d
        if k == "quality":
            s["quality"] = _clip(new, lo, 1)
        else:
            s["features"][k] = _clip(new, lo, 1)
    st = copy.deepcopy(settings)
    st.update(opt.get("settings_mod", {}))
    if opt.get("response") is not None:
        st["response"] = opt["response"]
    st.update({"agents": OPTION_AGENTS, "runs": 1, "days": days})
    return s, st


def test_options(spec, settings, progress=lambda *a: None):
    """Run the plan and each alternative at a smaller scale, same seed. Returns a list, plan first."""
    from .knowledge import library
    arche_key = spec["archetype"]
    arche = library()["archetypes"][arche_key]
    days = int(min(int(settings.get("days", 10)), OPTION_DAYS))
    opts = [{"id": "plan", "label": "Your plan, as entered", "why": "The baseline everything else is compared with.",
             "response": None, "spec_mod": {}, "model_mod": {}, "settings_mod": {}}]
    opts += candidates(spec, settings, arche_key, arche)
    base_spec, base_st = _apply(spec, settings, opts[0], days)
    cfg0, _ = compose(base_spec, base_st)
    seed = int(cfg0["simulation"]["seed"])
    rng = np.random.default_rng(seed)
    pop = Population(cfg0, rng)
    net = build_network(pop, cfg0, rng)
    out = []
    for i, o in enumerate(opts):
        progress(i / len(opts), f"Testing option {i + 1} of {len(opts)}: {o['label'].lower()}")
        s, st = _apply(spec, settings, o, days)
        cfg, _ = compose(s, st)
        for k, d in o.get("model_mod", {}).items():
            cfg["model"][k] = cfg["model"].get(k, 0) + d
        sim = Simulation(cfg, pop, net, seed + 7)
        for _ in range(int(cfg["simulation"]["hours"])):
            sim.step()
        m = metrics(sim.history_arrays())
        m["score"] = score(m)
        out.append({"id": o["id"], "label": o["label"], "why": o["why"],
                    "response": o.get("response"), **{k: round(v, 4) for k, v in m.items()}})
    base = out[0]["score"]
    for o in out:
        o["vs_plan"] = round(o["score"] - base, 4)
    best = max(out, key=lambda o: o["score"])
    best["best"] = True
    return {"options": out, "agents": OPTION_AGENTS, "days": days}


# ---------------------------------------------------------------------------- the call
def _bad(m):
    return m["opinion_change"] < -0.05 or m["churn"] > 0.04 or (m["against_end"] - m["against_start"]) > 0.08


def decide(k, people, tested, arche, spec, runs):
    w = words(arche, spec)
    opts = (tested or {}).get("options") or []
    plan = opts[0] if opts else None
    best = max(opts, key=lambda o: o["score"]) if opts else None
    gain = (best["score"] - plan["score"]) if plan else 0.0
    aware = people["overall"]
    m = {"opinion_change": k["opinion_change"], "churn": k["churn"],
         "against_end": k["negative_end"], "against_start": k["negative_start"]}
    bad = _bad(m)
    good = (k["opinion_change"] > 0.02 or k["adoption"] > 0.05) and not bad
    reasons = []
    pf, pa = aware["for"], aware["against"]
    if aware["heard"] < 0.12:
        reasons.append(f"Most people never heard about it: only {aware['heard'] * 100:.0f} in 100 did.")
    else:
        reasons.append(f"Of the people who heard about it, {pf * 100:.0f}% ended up for it and {pa * 100:.0f}% against.")
    if k["opinion_change"] <= -0.02:
        reasons.append(f"Overall feeling toward {w['org']} got worse ({k['opinion_change']:+.2f} on a −1 to +1 scale).")
    elif k["opinion_change"] >= 0.02:
        reasons.append(f"Overall feeling toward {w['org']} improved ({k['opinion_change']:+.2f} on a −1 to +1 scale).")
    else:
        reasons.append(f"Overall feeling toward {w['org']} barely moved ({k['opinion_change']:+.2f}).")
    if k["churn"] > 0.005:
        reasons.append(f"{k['churn'] * 100:.1f}% of {w['customers']} {w['churn']}.")
    if k["adoption"] > 0.002:
        reasons.append(f"{k['adoption'] * 100:.1f}% of {w['adopters']} {w['adopt']}.")
    better = best and best["id"] != "plan" and gain > 0.02
    if best and best["id"] != "plan" and better:
        reasons.append(f"Of the {len(opts) - 1} alternatives tested, \"{best['label'].lower()}\" did best: "
                       f"feeling {best['opinion_change']:+.2f} vs {plan['opinion_change']:+.2f} with your plan.")
    elif opts:
        reasons.append(f"None of the {len(opts) - 1} alternatives tested beat your plan by a meaningful margin.")

    if w["mode"] == "respond":
        if better:
            call, head = "change", f"Change your response: {best['label'].lower()}."
        else:
            call, head = "go", "Your planned response is the best of the options tested."
        if bad and not better:
            head += " Expect real damage either way; focus on limiting it."
    else:
        best_ok = best is not None and not _bad(best)
        if good and not better:
            call, head = "go", "Go ahead as planned."
        elif not bad and better:
            call, head = "go_with_changes", f"Go ahead, with one change: {best['label'].lower()}."
        elif not bad:
            call, head = "go", "Go ahead, but don't expect much: the public mostly shrugs."
        elif bad and better and best_ok:
            call, head = "change_first", f"Don't go ahead as it stands. With this change it becomes workable: {best['label'].lower()}."
        else:
            call, head = "dont", "Don't go ahead in this form."

    spread = abs(k.get("opinion_hi", k["opinion_change"]) - k.get("opinion_lo", k["opinion_change"]))
    margin = abs(gain)
    if runs >= 3 and spread < 0.05 and (margin > 0.03 or not opts):
        conf = "high"
    elif runs >= 2 and spread < 0.1:
        conf = "medium"
    else:
        conf = "low"
    return {"call": call, "headline": head, "reasons": reasons, "confidence": conf, "mode": w["mode"],
            "best_option": best["id"] if best else None}
