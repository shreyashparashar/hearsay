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


# ---------------------------------------------------------------------------- plain-language layer
def _share(x):
    return f"{x * 100:.0f}%"


def _in100(x, what=""):
    """'12 in every 100 people', 'about 4 in every 1,000', 'almost nobody'."""
    v = x * 100
    if v >= 1:
        return f"{v:.0f} in every 100 people{what}"
    if v * 10 >= 1:
        return f"about {v * 10:.0f} in every 1,000 people{what}"
    if v > 0:
        return f"fewer than 1 in 1,000 people{what}"
    return f"nobody{what}"


def _pct(x):
    return f"{x * 100:.1f}%" if x < 0.01 else f"{x * 100:.0f}%"


def people_summary(sim, pop, cards, w):
    """What each group thought at the end, among the people in it who heard about it."""
    o0, o1, aware = pop.opinion0, sim.opinion, sim.product_aware
    def split(mask):
        a = mask & aware
        na = max(int(a.sum()), 1)
        return {"heard": float(aware[mask].mean()) if mask.any() else 0.0,
                "for": float((o1[a] > 0.2).sum() / na), "against": float((o1[a] < -0.2).sum() / na),
                "for_before": float((o0[a] > 0.2).sum() / na), "against_before": float((o0[a] < -0.2).sum() / na)}
    overall = split(np.ones(pop.n, bool))
    overall["undecided"] = max(0.0, 1 - overall["for"] - overall["against"])
    groups = []
    for i, name in enumerate(pop.segment_names):
        g = split(pop.segment == i)
        g["undecided"] = max(0.0, 1 - g["for"] - g["against"])
        g["name"] = name
        card = next((c for c in cards if c["name"] == name), None)
        lean = "mostly for it" if g["for"] > g["against"] + 0.15 else \
            "mostly against it" if g["against"] > g["for"] + 0.15 else "split"
        d_for = g["for"] - g["for_before"]
        d_ag = g["against"] - g["against_before"]
        sent = {"mostly for it": "Mostly for it", "mostly against it": "Mostly against it", "split": "Split"}[lean]
        if abs(d_for) >= 0.05 or abs(d_ag) >= 0.05:
            moves = []
            if abs(d_for) >= 0.05:
                moves.append(f"support {'rose' if d_for > 0 else 'fell'} from {_share(g['for_before'])} to {_share(g['for'])}")
            if abs(d_ag) >= 0.05:
                moves.append(f"opposition {'rose' if d_ag > 0 else 'fell'} from {_share(g['against_before'])} to {_share(g['against'])}")
            sent += ": " + " and ".join(moves)
        else:
            sent += ", and they mostly kept the view they already had"
        sent += f". {_share(g['heard'])} of them heard about it."
        if card and card["drivers"]:
            dv = card["drivers"][0]
            sent += f" What moved them most: {dv['label']}."
        if card and card.get("churn") and card["churn"] > 0.005:
            sent += f" {_share(card['churn'])} of the {w['customers']} here {w['churn']}."
        if card and card.get("adoption") and card["adoption"] > 0.002:
            sent += f" {card['adoption'] * 100:.1f}% of the {w['adopters']} here {w['adopt']}."
        g["sentence"] = sent
        g["lean"] = lean
        groups.append(g)
    return {"overall": overall, "groups": groups}


def actions_summary(sim, pop, net, w):
    N = pop.n
    false = [n for n in sim.narr if n.truth is False]
    bel_false = np.zeros(N, bool)
    rej_false = np.zeros(N, bool)
    for n in false:
        st = sim.state[n.idx]
        bel_false |= (st == SPREADER) | (st == BELIEVER)
        rej_false |= st == REJECTER
    o0, o1 = pop.opinion0, sim.opinion
    won = (o0 <= 0.2) & (o1 > 0.2) & (o1 - o0 > 0.15)
    lost = (o0 >= -0.2) & (o1 < -0.2) & (o0 - o1 > 0.15)
    bought = sim.adopted & (sim.adopt_time >= 0)
    a = {"heard": float(sim.product_aware.mean()), "talked": float(sim.posted_ever.mean()),
         "spread_hostile": float(sim.posted_neg_ever.mean()), "believed_false": float(bel_false.mean()),
         "rejected_false": float(rej_false.mean()), "won_over": float(won.mean()), "turned_against": float(lost.mean()),
         "bought": float(bought.mean()), "left": float(sim.churned.mean()),
         "big_accounts_posting": len({e["text"] for e in sim.events if e["kind"] == "influencer"})}
    S = len(pop.segment_names)
    seg_n = np.maximum(np.bincount(pop.segment, minlength=S), 1)
    def top(mask):
        r = np.bincount(pop.segment, weights=mask, minlength=S) / seg_n
        i = int(np.argmax(r))
        return pop.segment_names[i], float(r[i])
    lines = [f"{_in100(a['heard']).capitalize()} heard about it, and {_in100(a['talked'])} said something about it online."]
    if a["won_over"] > 0.001 or a["turned_against"] > 0.001:
        lines.append(f"It won over {_in100(a['won_over'])} and turned {_in100(a['turned_against'])} against.")
    if a["spread_hostile"] > 0.0005:
        g, r = top(sim.posted_neg_ever)
        lines.append(f"{_in100(a['spread_hostile']).capitalize()} spread something hostile or false; "
                     f"the group doing most of it was {g} ({_pct(r)} of them).")
    if false:
        lines.append(f"The false claims were believed by {_in100(a['believed_false'])} "
                     f"and rejected by {_in100(a['rejected_false'])}.")
    if a["bought"] > 0.0005:
        lines.append(f"{_in100(a['bought']).capitalize()} {w['adopt']}.")
    if a["left"] > 0.0005:
        g, r = top(sim.churned)
        lines.append(f"{_in100(a['left']).capitalize()} {w['churn']}, mostly {g}.")
    if a["big_accounts_posting"]:
        lines.append(f"{a['big_accounts_posting']} of the most-followed accounts posted about it, "
                     "which is what carried it beyond friend circles.")
    a["lines"] = lines
    return a


def _template_plain(spec, decision, verdict, people, actions, tested, stories, w, timeline):
    opts = (tested or {}).get("options") or []
    better = sorted([o for o in opts if o["id"] != "plan" and o["vs_plan"] > 0.01], key=lambda o: -o["vs_plan"])
    worse_story = sorted([s for s in stories if s["valence"] < 0], key=lambda s: -s["believe_end"])
    good_story = sorted([s for s in stories if s["valence"] > 0], key=lambda s: -s["believe_end"])
    groups = sorted(people["groups"], key=lambda g: g["against"] - g["for"])
    change = [f"{o['label']}. {o['why']} (feeling {o['opinion_change']:+.2f} instead of {opts[0]['opinion_change']:+.2f})"
              for o in better[:4]]
    if not change:
        change = ["Nothing tested beat the plan by much; the plan's own details matter more than its timing."]
    bo = next((o for o in opts if o.get("best")), None)
    risk = worse_story[0]["label"] if worse_story else None
    hostile_group = groups[-1]["name"] if groups else "the most critical group"
    warm_group = groups[0]["name"] if groups else "supporters"
    prog = []
    if w["mode"] == "decide":
        if bo and bo["id"] in ("price", "quality", "tone", "pilot", "buzz"):
            prog.append({"when": "Before you announce", "what": bo["label"] + "."})
        prog.append({"when": "Before you announce", "what": "Write down the three questions people will ask"
                     + (f", starting with the one behind \"{risk}\"" if risk else "") + ", and answer them in plain words."})
        prog.append({"when": "Day one", "what": f"Lead with what helps people most, and get it first to {warm_group}, "
                     "who are most likely to pass it on warmly."})
        if bo and bo.get("response") and bo["response"]["type"] not in ("none",):
            prog.append({"when": f"Within {bo['response']['hour']} hours", "what": bo["label"] + "."})
        prog.append({"when": "Days 2 to 5", "what": f"Watch {hostile_group}. If the share of people against it keeps rising "
                     f"past {decision.get('_peak', 0.25) * 100:.0f}%, act on the strongest complaint rather than restating the plan."})
        prog.append({"when": "After a week", "what": f"Count how many {w['adopters']} actually {w['adopt']}; talk is louder than behaviour."})
    else:
        if bo and bo.get("response") and bo["response"]["type"] != "none":
            prog.append({"when": f"Within {bo['response']['hour']} hours", "what": bo["label"] + "."})
        if risk:
            prog.append({"when": "Same day", "what": f"Answer \"{risk}\" directly, with evidence people can check."})
        prog.append({"when": "Days 1 to 3", "what": f"Speak to {hostile_group} first; they are where the anger is."})
        prog.append({"when": "Within a week", "what": "Show a concrete change, not just a statement, and say when the next update comes."})
    watch = []
    if risk:
        watch.append(f"How many people repeat \"{risk}\".")
    watch.append(f"Whether {hostile_group} keep talking after day three.")
    if good_story:
        watch.append(f"Whether \"{good_story[0]['label']}\" keeps spreading on its own.")
    return {"bottom_line": verdict[1],
            "people_thought": " ".join(f"{g['name'].capitalize()}: {g['sentence']}" for g in people["groups"]),
            "who_did_what": " ".join(actions["lines"]),
            "what_to_change": change, "program": prog, "watch_for": watch, "written_by": "template"}


def plain_report(spec, decision, verdict, people, actions, tested, stories, w, timeline, analogs, patterns, k):
    base = _template_plain(spec, decision, verdict, people, actions, tested, stories, w, timeline)
    if not llm_config():
        return base
    try:
        facts = {
            "event": spec.get("summary") or spec.get("title"), "organisation": spec.get("brand"),
            "kind_of_decision": "deciding whether to go ahead" if w["mode"] == "decide" else "responding to something that already happened",
            "computed_call": decision["call"], "computed_headline": decision["headline"], "reasons": decision["reasons"],
            "groups": [{"name": g["name"], "heard": round(g["heard"], 2), "for": round(g["for"], 2),
                        "against": round(g["against"], 2), "for_before": round(g["for_before"], 2),
                        "against_before": round(g["against_before"], 2)} for g in people["groups"]],
            "what_people_did": actions["lines"],
            "stories": [{"story": s["label"], "good_or_bad_for_org": s["valence"], "false": s["truth"] is False,
                         "heard_by": round(s["aware_end"], 2), "believed_by": round(s["believe_end"], 2)} for s in stories],
            "options_tested": [{"option": o["label"], "feeling_change": o["opinion_change"], "lost_share": o["churn"],
                                "took_up_share": o["adoption"], "better_than_plan_by": o["vs_plan"]}
                               for o in (tested or {}).get("options", [])],
            "timeline": [f"{_day(e['hour'])}: {e['text']}" for e in timeline[:14]],
            "past_cases": [f"{a['name']} ({a['year']}): {(a.get('lessons') or [a['summary']])[0]}" for a in analogs[:3]],
            "patterns": [p["title"] for p in patterns], "words": {k_: v for k_, v in w.items() if k_ != "mode"},
        }
        raw = chat([{"role": "system", "content":
                     "You explain the result of a public-reaction simulation to a busy decision-maker who is not an "
                     "expert. Use plain everyday words, short sentences, numbers as 'X in 100 people'. Never invent "
                     "numbers that are not in the facts. Your advice MUST agree with computed_call and computed_headline. "
                     "Return ONLY JSON with keys: bottom_line (2 sentences: the answer, then the main reason), "
                     "people_thought (3-5 sentences, group by group, what they thought and why), who_did_what (3-5 "
                     "sentences: who heard, who talked, who spread what, who bought or left, who changed their mind), "
                     "what_to_change (array of 2-5 short concrete changes, best first, grounded in options_tested), "
                     "program (array of 4-6 objects {when, what}: the plan to follow, in order, concrete), "
                     "watch_for (array of 2-3 early warning signs). Remind nobody that it is a simulation; the page does."},
                    {"role": "user", "content": json.dumps(facts)}])
        j = parse_json(raw)
        out = dict(base)
        for key in ("bottom_line", "people_thought", "who_did_what"):
            if isinstance(j.get(key), str) and j[key].strip():
                out[key] = j[key].strip()
        for key in ("what_to_change", "watch_for"):
            if isinstance(j.get(key), list) and j[key]:
                out[key] = [str(x)[:300] for x in j[key] if str(x).strip()][:6]
        if isinstance(j.get("program"), list) and j["program"]:
            prog = [{"when": str(p.get("when", ""))[:60], "what": str(p.get("what", ""))[:320]}
                    for p in j["program"] if isinstance(p, dict) and p.get("what")]
            if prog:
                out["program"] = prog[:7]
        out["written_by"] = "model"
        return out
    except Exception:
        return base


LINE_TEMPLATES = {
    "pos": ["Honestly this is good news. {label}.", "Saw this about {org}: {label}. Not bad at all.",
            "Finally something sensible from {org}.", "Sharing because people should see this: {label}.",
            "Didn't expect to like it, but I do.", "This is the kind of thing that makes me trust {org} more."],
    "neg": ["Are we really just going to accept this? {label}.", "{org} thinks we won't notice. We noticed.",
            "Read this before you defend them: {label}.", "Not okay. Not okay at all.",
            "Every time I give {org} a chance, something like this.", "Spread the word: {label}."],
    "mid": ["Has anyone actually looked into this? {label}.", "Hearing a lot about {label}. Thoughts?",
            "Not sure what to make of this yet.", "Interesting. Let's see how it plays out.",
            "Everyone's talking about {org} today.", "Okay, what's the real story here?"],
}


def story_lines(narratives, spec, use_model=True):
    """A few things people might actually type when they share each story (shown in the live view)."""
    org = spec.get("brand") or "them"
    out = {}
    for n in narratives:
        v = float(n.get("valence") if isinstance(n.get("valence"), (int, float)) else 0)
        key = "pos" if v > 0.15 else "neg" if v < -0.15 else "mid"
        label = n.get("label", n["id"]).rstrip(".")
        out[n["id"]] = [t.format(label=label, org=org) for t in LINE_TEMPLATES[key]]
    if not use_model or not llm_config():
        return out, "template"
    try:
        payload = [{"id": n["id"], "story": n.get("label"), "what_it_is": n.get("description", ""),
                    "good_or_bad_for_org": n.get("valence"), "false_rumour": n.get("truth") is False} for n in narratives]
        raw = chat([{"role": "system", "content":
                     "For each story, write 6 short social posts (max 22 words each) that different ordinary people "
                     "would write when sharing it: vary voice, mood and length; some sarcastic, some sincere, some "
                     "questioning. No hashtags, no slurs, no real people's names. Return ONLY JSON {story_id: [6 posts]}."},
                    {"role": "user", "content": f"Event: {spec.get('summary') or spec.get('title')}\n"
                     f"Organisation: {org}\nStories: {json.dumps(payload)}"}])
        j = parse_json(raw)
        for k, v in j.items():
            if k in out and isinstance(v, list):
                lines = [str(x).strip()[:180] for x in v if str(x).strip()]
                if len(lines) >= 3:
                    out[k] = lines[:8]
        return out, "model"
    except Exception:
        return out, "template"


def build(spec, cfg, extras, q, sim, pop, net, runs, tested=None, network=None):
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
        "negative_end": float(q["negative_share_p50"][-1]), "positive_end": float(q["positive_share_p50"][-1]),
        "opinion_lo": float(q["mean_opinion_p10"][-1] - q["mean_opinion_p10"][0]),
        "opinion_hi": float(q["mean_opinion_p90"][-1] - q["mean_opinion_p90"][0]),
    }
    k["opinion_change"] = k["opinion_end"] - k["opinion_start"]
    title, line = verdict(k, spec)
    from .advisor import decide, words
    from .knowledge import library
    arche = library()["archetypes"][spec["archetype"]]
    w = words(arche, spec)

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

    people = people_summary(sim, pop, cards, w)
    actions = actions_summary(sim, pop, net, w)
    decision = decide(k, people, tested, arche, spec, runs)
    decision["_peak"] = k["negative_peak"]
    plain = plain_report(spec, decision, (title, line), people, actions, tested, stories, w, timeline,
                         extras["analogs"], extras["patterns"], k)
    decision.pop("_peak", None)

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
        "decision": decision, "plain": plain, "people": people, "actions": actions, "options": tested,
        "words": w, "network": network,
        "briefing": "\n\n".join([plain["bottom_line"], plain["people_thought"], plain["who_did_what"]]),
        "kpis": k, "timeline": timeline, "segments": cards, "voices": vs, "stories": stories, "series": series,
        "history": history, "analogs": extras["analogs"], "patterns": extras["patterns"], "crowd": crowd,
        "meta": {"agents": N, "ties": int(net.n_edges), "hours": int(len(hours)), "runs": runs,
                 "segments": pop.segment_names, "top_followers": int(net.followers.max())},
    }
