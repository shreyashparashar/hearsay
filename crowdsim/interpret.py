"""Reads what the user typed and uploaded and turns it into an event spec the simulator understands.

Any OpenAI-compatible chat endpoint works (free options: Google AI Studio / Gemini, OpenRouter free
models, Groq, or a local Ollama model). Configure with environment variables:

  GEMINI_API_KEY=...                       easiest free option (uses Gemini's OpenAI-compatible endpoint)
  or CROWDSIM_LLM_BASE_URL / CROWDSIM_LLM_API_KEY / CROWDSIM_LLM_MODEL for any other provider
  CROWDSIM_VISION_MODEL                    optional separate model for images
  CROWDSIM_USE_OLLAMA=1                    use a local Ollama server (no key)

Without any of these, a keyword reader produces a rougher spec so the app still works.
"""
import base64
import json
import os
import re
import time
import urllib.error
import urllib.request

from .knowledge import FEATURES, library

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


def llm_config():
    base = os.getenv("CROWDSIM_LLM_BASE_URL")
    key = os.getenv("CROWDSIM_LLM_API_KEY", "")
    model = os.getenv("CROWDSIM_LLM_MODEL")
    if not base and os.getenv("GEMINI_API_KEY"):
        base, key, model = GEMINI_BASE, os.getenv("GEMINI_API_KEY"), model or "gemini-flash-latest"
    if not base and os.getenv("CROWDSIM_USE_OLLAMA"):
        base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        model = model or "qwen2.5vl:7b"
    if not base or not model:
        return None
    return {"base": base.rstrip("/"), "key": key, "model": model,
            "vision_model": os.getenv("CROWDSIM_VISION_MODEL", model)}


def chat(messages, cfg=None, json_mode=True, timeout=120, vision=False):
    cfg = cfg or llm_config()
    if not cfg:
        raise RuntimeError("no model configured")
    primary = cfg["vision_model"] if vision else cfg["model"]
    # Busy/overloaded models (503, 429, 500) get retried, then a lighter backup model is tried.
    fallback = os.getenv("CROWDSIM_FALLBACK_MODEL",
                         "gemini-flash-lite-latest" if cfg["base"] == GEMINI_BASE else "")
    models = [primary] + ([fallback] if fallback and fallback != primary else [])
    headers = {"Content-Type": "application/json"}
    if cfg["key"]:
        headers["Authorization"] = f"Bearer {cfg['key']}"

    def post(b):
        req = urllib.request.Request(cfg["base"] + "/chat/completions", json.dumps(b).encode(), headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    last_err = None
    for model in models:
        body = {"model": model, "messages": messages, "temperature": 0.3}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        for attempt in range(3):
            try:
                data = post(body)
                return data["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="ignore")[:300]
                if e.code == 400 and "response_format" in body:   # some providers reject it; retry without
                    body.pop("response_format")
                    continue
                last_err = RuntimeError(f"model request failed ({e.code}): {detail}")
                if e.code in (429, 500, 503):
                    time.sleep(2 * (attempt + 1))   # wait 2s, then 4s, then 6s
                    continue
                if e.code == 404:                   # model unavailable: go straight to the backup
                    break
                raise last_err from e
            except (urllib.error.URLError, TimeoutError) as e:
                last_err = RuntimeError(f"model request failed (network): {e}")
                time.sleep(2 * (attempt + 1))
    raise last_err


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _system_prompt():
    arche = library()["archetypes"]
    kinds = "\n".join(f"  - {k}: {v['label']}" for k, v in arche.items())
    return f"""You turn an announcement, policy, programme, news item or event into inputs for a simulator of how
the public will react. It can be about a company, a product, a government policy or programme, a country,
a politician or an economic or geopolitical development. You may receive text, images (product photos,
ads, screenshots, logos, charts), or both. Think like a seasoned communications and policy strategist who
knows how real crowds behaved in past events, from brand launches to tax reforms, wars and market crashes.

Return ONLY a JSON object with exactly these keys:
{{
  "title": short name for the event,
  "brand": the company, government, organisation, country or person at the centre ("" if none),
  "category": product, sector or policy area,
  "summary": 1-2 plain sentences of what happened, as the public would hear it,
  "archetype": one of:
{kinds}
  "features": {{
     "valence": -1..1 how it first reflects on the organisation at the centre in the eyes of most people,
     "emotionality": 0..1 how strongly it makes people feel something,
     "identity": 0..1 how much it touches politics, values or group identity,
     "lean": -1..1 which side of the cultural axis it flatters (-1 progressive-coded, +1 traditional-coded, 0 neither),
     "harm": 0..1 physical, financial or personal harm to people,
     "responsibility": 0..1 how much the public will hold the organisation responsible,
     "hype": 0..1 how anticipated it was,
     "price": 0..1 how central price or money is,
     "prominence": 0..1 how well known the organisation is,
     "novelty": 0..1 how surprising it is,
     "credibility": 0..1 how believable the core claim is
  }},
  "quality": -1..1 how good the product/experience really is if people try it (0 if not a product),
  "substitutes": 0..1 how easy it is for customers to switch to an alternative,
  "audience": 3 to 5 groups, each {{"name": plain words, "share": fraction of the population,
       "baseline_opinion": -1..1 attitude to the organisation before this, "can_adopt": true if they could buy,
       use, sign up for or comply with it,
       "already_customer": 0..1 share of the group already using it, "need": 0..1,
       "price_sensitivity": 0..1, "ideology": -1..1 (only if relevant, else 0), "note": why this group matters}}.
       Always include the general public that won't act but will talk. For policies include who gains, who
       pays, supporters and opponents of the government. Shares should sum to about 1.
  "stories": 2 to 5 secondary stories that would plausibly emerge on their own (rumors, memes, boycott calls,
       expert takes, competitor jabs, leaks), each {{"id": snake_case, "label": short phrase, "description":
       what people say, "kind": rumor|ugc|news|movement|ad, "truth": true|false|null, "valence": -1..1,
       "credibility": 0..1, "emotionality": 0..1, "identity": 0..1, "lean": -1..1, "start_hour": hours after the event}},
  "image_observations": list of short factual notes about what the images show and how the public may read them ([] if none),
  "strengths": up to 3 short phrases, "risks": up to 3 short phrases
}}
Be calibrated: most events are not culture-war events (identity near 0), most announcements are not crises.
Pick government_policy for any law, tax, scheme, subsidy, ban or public programme, even if it is popular.
Do not invent facts about real people; describe likely reactions, not certainties."""


def interpret(text, images=(), context=""):
    """images: list of (bytes, mime). Returns a normalised spec dict."""
    cfg = llm_config()
    if cfg:
        try:
            content = [{"type": "text", "text": f"Context from the user: {context or 'none'}\n\nWhat happened:\n{text or '(see images)'}"}]
            for data, mime in images:
                content.append({"type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{base64.b64encode(data).decode()}"}})
            raw = chat([{"role": "system", "content": _system_prompt()}, {"role": "user", "content": content}],
                       cfg, vision=bool(images))
            spec = normalise(parse_json(raw))
            spec["reader"] = f"model: {cfg['vision_model'] if images else cfg['model']}"
            return spec
        except Exception as e:   # fall back rather than fail the user
            spec = keyword_reader(text, context)
            spec["reader"] = "keyword reader"
            spec["reader_note"] = f"The model call failed ({str(e)[:160]}), so a keyword reader was used."
            return spec
    spec = keyword_reader(text, context)
    spec["reader"] = "keyword reader"
    spec["reader_note"] = ("No AI model is configured, so a keyword reader filled this in. Set GEMINI_API_KEY "
                           "(free) to have images and text actually understood." if images or text else "")
    return spec


def _clip(x, lo, hi, default):
    try:
        return max(lo, min(hi, float(x)))
    except (TypeError, ValueError):
        return default


def normalise(s):
    arche = library()["archetypes"]
    out = {"title": str(s.get("title") or "Untitled event")[:120], "brand": str(s.get("brand") or "")[:80],
           "category": str(s.get("category") or "")[:80], "summary": str(s.get("summary") or "")[:600]}
    a = str(s.get("archetype") or "product_launch")
    out["archetype"] = a if a in arche else "product_launch"
    f = s.get("features") or {}
    out["features"] = {k: _clip(f.get(k), -1 if k in ("valence", "lean") else 0, 1, 0.0) for k in FEATURES}
    out["features"]["credibility"] = _clip(f.get("credibility"), 0, 1, 0.75)
    out["quality"] = _clip(s.get("quality"), -1, 1, 0.0)
    out["substitutes"] = _clip(s.get("substitutes"), 0, 1, 0.5)
    aud = []
    for g in (s.get("audience") or [])[:6]:
        if not isinstance(g, dict) or not g.get("name"):
            continue
        aud.append({"name": str(g["name"])[:40], "share": _clip(g.get("share"), 0.005, 1, 0.1),
                    "baseline_opinion": _clip(g.get("baseline_opinion"), -1, 1, 0.0),
                    "can_adopt": bool(g.get("can_adopt", False)),
                    "already_customer": _clip(g.get("already_customer"), 0, 1, 0.0),
                    "need": _clip(g.get("need"), 0, 1, 0.5),
                    "price_sensitivity": _clip(g.get("price_sensitivity"), 0, 1, 0.5),
                    "ideology": _clip(g.get("ideology"), -1, 1, 0.0), "note": str(g.get("note") or "")[:200]})
    out["audience"] = aud
    stories = []
    for i, st in enumerate((s.get("stories") or [])[:6]):
        if not isinstance(st, dict):
            continue
        sid = re.sub(r"[^a-z0-9_]", "_", str(st.get("id") or f"story_{i}").lower())[:40] or f"story_{i}"
        kind = st.get("kind") if st.get("kind") in ("rumor", "ugc", "news", "movement", "ad") else "ugc"
        truth = st.get("truth")
        stories.append({"id": sid, "label": str(st.get("label") or sid.replace("_", " "))[:60],
                        "description": str(st.get("description") or "")[:240], "kind": kind,
                        "truth": truth if isinstance(truth, bool) else None,
                        "valence": _clip(st.get("valence"), -1, 1, -0.3),
                        "credibility": _clip(st.get("credibility"), 0, 1, 0.5),
                        "emotionality": _clip(st.get("emotionality"), 0, 1, 0.6),
                        "identity": _clip(st.get("identity"), 0, 1, 0.0),
                        "lean": _clip(st.get("lean"), -1, 1, 0.0),
                        "start_hour": int(_clip(st.get("start_hour"), 0, 600, 12))})
    out["stories"] = stories
    for k in ("image_observations", "strengths", "risks"):
        out[k] = [str(x)[:200] for x in (s.get(k) or []) if x][:6]
    return out


# --------------------------------------------------------------------------- keyword fallback
LEX = {
    "safety_defect": ["fire", "explod", "injur", "recall", "unsafe", "burn", "defect", "overheat", "crash", "death", "died", "toxic", "contamina"],
    "data_breach": ["breach", "hack", "data leak", "leaked data", "password", "personal data", "privacy", "exposed data", "data of"],
    "price_change": ["price", "subscription", "fee", "increase", "hike", "charge", "paywall", "cost more", "tier"],
    "rebrand": ["logo", "rebrand", "rename", "new name", "redesign", "new look", "identity"],
    "values_controversy": ["pride", "woke", "boycott", "political", "politic", "diversity", "activist", "religio", "gender", "trans", "conservative", "liberal"],
    "outage": ["outage", "down", "offline", "not working", "service disruption", "crashed"],
    "trust_scandal": ["fraud", "scandal", "lied", "cover", "fired", "resign", "lawsuit", "investigation", "harass", "cheat"],
    "ad_misfire": ["ad ", "advert", "commercial", "campaign", "tone-deaf", "tone deaf"],
    "service_incident": ["video", "customer", "employee", "staff", "viral", "passenger", "rude"],
    "disaster": ["spill", "collapse", "explosion", "disaster", "pollut"],
    "viral_fad": ["trend", "challenge", "meme", "craze", "tiktok"],
    "financial_panic": ["bank", "withdraw", "run on", "shortage", "panic", "sell-off", "insolven"],
    "government_policy": ["policy", "government", "ministry", "scheme", "yojana", "law", "bill", "tax", "subsidy",
                          "compulsory", "mandatory", "fine of", "fine and", "licence", "license", "state will",
                          "will make", "rule", "rules", "eligible", "citizens", "municipal", "fee waiver",
                          "regulation", "mandate", "ban ", "budget", "reform", "parliament", "cabinet", "programme",
                          "program", "welfare", "gst", "tariff"],
    "geopolitical_crisis": ["war", "attack", "border", "sanction", "military", "invasion", "missile", "terror",
                            "diplomat", "embassy", "ceasefire", "troops", "airstrike"],
    "economic_shock": ["inflation", "recession", "crash", "market fell", "stock market", "currency", "rupee",
                       "unemployment", "prices rise", "price rise", "fuel price", "interest rate", "layoff"],
    "public_health": ["vaccine", "virus", "pandemic", "outbreak", "disease", "lockdown", "covid", "hospital",
                      "health advisory", "epidemic"],
    "political_moment": ["election", "minister", "candidate", "party", "speech", "politician", "vote", "rally",
                         "prime minister", "president said"],
    "labor_dispute": ["strike", "union", "layoffs", "laid off", "workers", "employees", "work hours", "fired staff"],
    "product_launch": ["launch", "unveil", "introduc", "announc", "release", "new ", "available", "pre-order", "debut", "ships", "coming soon"],
}
POS = ["best", "new", "faster", "better", "love", "amazing", "free", "innovative", "breakthrough", "improved", "award", "record"]
NEG = ["worst", "angry", "outrage", "dangerous", "fail", "broken", "scam", "lie", "hate", "scandal", "problem", "victim", "lost", "harm"]
HOT = ["!", "shocking", "outrage", "viral", "furious", "dead", "children", "kids", "fire", "boycott", "scandal"]


def keyword_reader(text, context=""):
    t = f" {(text or '')} {(context or '')} ".lower()
    def hits(words):   # word-start matches, so "ad" doesn't fire inside "had"
        return sum(len(re.findall(r"\b" + re.escape(w.strip()), t)) for w in words)
    scores = {a: hits(ws) for a, ws in LEX.items()}
    scores["product_launch"] *= 0.7   # generic words; only wins when nothing else fits
    arche = max(scores, key=scores.get) if any(scores.values()) else "product_launch"
    pos, neg = hits(POS), hits(NEG)
    crisis = library()["archetypes"][arche].get("crisis", False)
    valence = max(-0.9, min(0.9, (pos - neg) * 0.15 + (-0.5 if crisis else 0.35)))
    emo = min(1.0, 0.4 + 0.08 * (hits(HOT[1:]) + t.count("!")) + (0.2 if crisis else 0))
    stop = {"viral", "video", "breaking", "new", "the", "a", "an", "today", "this", "our", "we", "i", "users",
            "people", "customers", "report", "reports", "news", "update", "after", "just", "why", "how", "it",
            "rumors", "rumours", "hackers", "rebrand", "tomorrow", "yesterday", "monday", "tuesday", "wednesday",
            "thursday", "friday", "saturday", "sunday", "starting", "next", "early", "beta", "ceo",
            "inflation", "border", "workers", "government", "viral", "from", "prices", "state", "january",
            "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
            "december", "all", "every", "free", "india", "indian"}
    cands = []
    for m in re.finditer(r"\b[A-Z][a-zA-Z0-9]+\b", text or ""):
        w = m.group(0)
        if w.lower() in stop:
            continue
        before = (text or "")[:m.start()].rstrip()
        initial = not before or before[-1] in ".!?:\n"
        rank = 0 if re.search(r"[a-z][A-Z]", w) else (2 if initial else 1)   # QuickBank > mid-sentence > first word
        cands.append((rank, m.start(), w))
    brand = min(cands)[2] if cands else ""
    if arche in ("government_policy", "public_health", "geopolitical_crisis", "economic_shock") and \
            (not brand or not re.search(r"[a-z][A-Z]|^[A-Z]{2,}$", brand)) and not re.search(r"\b(we|our)\b", t):
        brand = {"public_health": "the health authorities"}.get(arche, "the government")
    first = re.split(r"(?<=[.!?])\s", (text or "Untitled event").strip())[0]
    title = first if len(first) <= 70 else first[:70].rsplit(" ", 1)[0] + "…"
    spec = normalise({
        "title": title,
        "brand": brand, "summary": (text or "")[:300], "archetype": arche,
        "features": {"valence": valence, "emotionality": emo,
                     "identity": 0.8 if arche == "values_controversy" else 0.5 if arche in (
                         "political_moment", "geopolitical_crisis") else 0.2 if arche == "government_policy" else 0.05,
                     "harm": 0.7 if arche in ("safety_defect", "disaster") else (0.4 if crisis else 0.0),
                     "responsibility": 0.7 if crisis else 0.2, "hype": 0.5 if arche == "product_launch" else 0.1,
                     "price": 0.8 if arche in ("price_change", "economic_shock") else
                     (0.6 if any(c in t for c in ("$", "₹", "€", "£", "price", "tax", "cost")) else 0.3),
                     "prominence": 0.6, "novelty": 0.7, "credibility": 0.75},
        "quality": 0.2, "substitutes": 0.5,
    })
    return spec
