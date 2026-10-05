"""One tick = one hour. Every hour, for every agent:

  1. Am I online? (personal activity x time-of-day curve in my own time zone)
  2. How much attention is left? Macro context (a busy news week, a war, an election)
     shrinks everyone's attention for this story.
  3. For every story in circulation (the announcement, rumors, memes, boycott calls,
     denials, reviews, incident videos...):
       - people spreading it may post (more if emotional, aroused, expressive, story is fresh)
       - posts land in followers' feeds and wait there until they log in
       - I can also catch it on the trending feed or through mass media
       - first time I see it I accept or reject it: credibility, my skepticism, whether it fits
         what I already think, my identity (values-coded stories split people), how many friends
         believe it, trust in the source, emotional pull, whether I've seen it debunked
       - accepting moves my opinion (negative news and identity threats hit harder) and arousal;
         outrage makes me share
       - spreaders get bored or find everyone already knows (stifling)
       - rejected claims repeated often enough can still stick (illusory truth)
       - debunks un-convince some believers, only partly (continued influence), and spread
         word of the claim they deny (Streisand effect)
       - newsrooms pick a story up once enough people believe it (agenda setting: tipping point)
  4. My opinion drifts toward what my friends post, if not too far from mine (bounded
     confidence), and slowly relaxes to my baseline.
  5. Behaviour: potential customers may buy (Bass-style hazard). Existing customers who turn
     hostile may leave (churn, cancellations, withdrawals). Buyers experience the product later:
     reviews spread, and a share of them hit defects and post incident stories (micro events
     that can escalate into macro news).

The whole social step is ONE sparse-matrix x dense-matrix product per hour.
"""
import numpy as np

UNAWARE, SPREADER, BELIEVER, REJECTER = 0, 1, 2, 3

DEFAULT_MODEL = dict(
    # exposure
    feed_visibility=0.4, feed_decay=0.85, algo_boost=3.0, trend_cap=0.03, post_rate=0.3,
    # acceptance (logit weights)
    accept_bias=0.0, w_credibility=2.0, w_skepticism=3.0, w_confirmation=1.5,
    w_social_proof=2.0, w_trust=1.0, w_prior_debunk=2.5, w_emotion_belief=1.5,
    w_identity=2.0,            # values-coded stories are believed by the side they flatter
    identity_valence=1.2,      # ...and feel good/bad depending on your side
    # sharing
    share_bias=-3.0, w_emotion=3.0, w_arousal=1.5, w_expressive=4.0,
    # story lifecycle
    forget_rate=0.02, stifle_rate=0.1, novelty_halflife=36.0,
    repetition_effect=0.01, correction_efficacy=0.6, continued_influence=0.5, streisand=0.15,
    # opinions & emotion
    opinion_impact=0.4, negativity_bias=0.5, social_influence=0.05,
    confidence_bound=0.5, opinion_relax=0.002, arousal_gain=0.6, arousal_decay=0.92,
    # behaviour
    adopt_base_rate=0.002, a_opinion=3.0, a_need=1.5, a_price=1.0, a_peer=3.0,
    a_innov=1.0, a_bias=-2.0, experience_delay=48, experience_impact=0.4, review_rate=0.15,
    churn_rate=0.003, churn_threshold=-0.25, defect_rate=0.0,
    defect_stop_hour=1e9,      # a recall/fix stops new incidents from this hour
)

DIURNAL = np.array([.25, .15, .10, .08, .08, .12, .30, .55, .70, .75, .75, .80,
                    .85, .80, .75, .75, .80, .85, .95, 1.0, 1.0, .95, .75, .45], np.float32)

SOURCE_BY_KIND = {"official": "brand", "debunk": "brand", "response": "brand", "ad": "brand",
                  "news": "media"}


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


class Narrative:
    """A story in circulation. `start` and `media` windows are absolute hours."""

    def __init__(self, d, idx, p):
        self.idx = idx
        self.id = d["id"]
        self.label = d.get("label", self.id.replace("_", " "))
        self.kind = d.get("kind", "news")
        self.valence = float(d.get("valence", 0.0))          # -1 bad for the brand .. +1 good
        self.credibility = float(d.get("credibility", 0.5))
        self.emotionality = float(d.get("emotionality", 0.5))
        self.identity = float(d.get("identity", 0.0))         # 0 neutral .. 1 pure culture-war
        self.lean = float(d.get("lean", 0.0))                 # -1 flatters progressive .. +1 traditional
        self.start = int(d.get("start", 0))
        self.about_product = bool(d.get("about_product", True))
        self.truth = d.get("truth")
        self.source = d.get("source", SOURCE_BY_KIND.get(self.kind))
        self.seed = d.get("seed") or {}
        self.halflife = float(d.get("novelty_halflife", p["novelty_halflife"]))
        self.media = [(int(m["start"]), int(m["end"]), float(m["intensity"])) for m in d.get("media", [])]
        self.pickup = d.get("media_pickup")
        self.picked_up_at = None
        self.debunks = d.get("debunks")
        self.debunk_target = None
        self.corrected = 0
        self.description = d.get("description", "")

    def media_intensity(self, t):
        return sum(i for s, e, i in self.media if s <= t < e)

    def novelty(self, t):
        return 0.5 ** (max(t - self.start, 0) / self.halflife)


def attention_curve(cfg, hours):
    """Macro attention available for this story, per hour (1 = nothing else going on)."""
    ctx = cfg.get("context") or {}
    a = np.full(hours + 1, float(ctx.get("attention", 1.0)), np.float32)
    for d in ctx.get("attention_shocks", []):   # e.g. a competing mega-event
        a[int(d["start"]):int(d["end"])] *= float(d["level"])
    return np.clip(a, 0.05, 1.0)


class Simulation:
    def __init__(self, cfg, pop, net, seed, snapshot_agents=0, snapshot_every=6):
        self.pop, self.net = pop, net
        self.p = p = {**DEFAULT_MODEL, **(cfg.get("model") or {})}
        self.rng = np.random.default_rng(seed)
        sim = cfg.get("simulation") or {}
        self.hours = int(sim.get("hours", 168))
        self.start_hour = int(sim.get("start_hour_of_day", 9))
        prod = cfg.get("product") or {}
        self.quality = prod.get("quality")
        self.attn = attention_curve(cfg, self.hours + 2)

        defs = list(cfg["narratives"])
        ids0 = {d["id"] for d in defs}
        if self.quality is not None and "user_reviews" not in ids0:
            q = float(self.quality)
            defs.append(dict(id="user_reviews", label="buyer reviews", kind="review", valence=q,
                             credibility=0.7, emotionality=0.3 + 0.4 * abs(q), start=0,
                             novelty_halflife=1e9, description="Posts from people who bought and used it."))
        if p["defect_rate"] > 0 and "user_incidents" not in ids0:
            defs.append(dict(id="user_incidents", label="buyer incident posts", kind="ugc", valence=-0.7,
                             credibility=0.65, emotionality=0.85, start=0, novelty_halflife=1e9,
                             media_pickup={"threshold": 0.01, "delay": 4, "duration": 36, "intensity": 0.04},
                             description="Photos and videos from buyers whose product failed them."))
        self.narr = [Narrative(d, i, p) for i, d in enumerate(defs)]
        ids = {n.id: n for n in self.narr}
        if len(ids) != len(self.narr):
            raise ValueError("narrative ids must be unique")
        for n in self.narr:
            if n.debunks:
                if n.debunks not in ids:
                    raise ValueError(f"{n.id} debunks unknown narrative {n.debunks!r}")
                n.debunk_target = ids[n.debunks].idx
        self.debunkers = {n.idx: [d for d in self.narr if d.debunk_target == n.idx] for n in self.narr}
        self.review = ids.get("user_reviews")
        self.incident = ids.get("user_incidents")

        K, N = len(self.narr), pop.n
        self.K = K
        self.state = np.zeros((K, N), np.int8)
        self.opinion = pop.opinion0.copy()
        self.arousal = np.zeros(N, np.float32)
        self.adopted = pop.adopted0.copy()
        self.churned = np.zeros(N, bool)
        self.adopt_time = np.full(N, -10**6, np.int32)
        self.product_aware = self.adopted.copy()
        self.X = np.zeros((N, 2 * K + 3), np.float32)
        self._zeros = np.zeros(N, np.float32)
        self.feed = np.zeros((K, N), np.float32)
        self.t = 0
        self.tracker = None                      # optional live view of a slice of the network
        self.posted_ever = np.zeros(N, bool)     # who said anything at all
        self.posted_neg_ever = np.zeros(N, bool) # who spread something hostile or false
        self.history, self.events = [], []
        self.incidents = 0
        S = len(pop.segment_names)
        self.seg_n = np.maximum(np.bincount(pop.segment, minlength=S), 1)
        eligible = pop.can_adopt & ~pop.adopted0
        self.eligible = eligible
        self.seg_eligible = np.bincount(pop.segment, weights=eligible, minlength=S)
        self.seg_customers = np.bincount(pop.segment, weights=pop.adopted0, minlength=S)
        self.n_eligible = max(int(eligible.sum()), 1)
        self.n_customers = int(pop.adopted0.sum())
        # notable accounts: the top 20 by followers get their posts logged as events
        top = net.influencers[:20]
        self.notable = {int(i): int(net.followers[i]) for i in top}
        self._notable_logged = {n.idx: 0 for n in self.narr}
        self._milestones = {n.idx: 0 for n in self.narr}
        self._last_net_sign = 0
        self._turn_run, self._turn_sign = 0, 0
        # crowd snapshots for the dashboard: a fixed sample, sorted by segment then community
        self.snap = None
        if snapshot_agents:
            rng = np.random.default_rng(1)
            idx = rng.choice(N, min(snapshot_agents, N), replace=False)
            idx = idx[np.lexsort((net.community[idx], pop.segment[idx]))]
            self.snap = dict(idx=idx, every=snapshot_every, opinion=[], flags=[], hours=[])

    def log(self, kind, text, story=None):
        self.events.append(dict(hour=int(self.t), kind=kind, text=text[:1].upper() + text[1:], story=story))

    # ---------------------------------------------------------------- helpers
    def _valence(self, n, idx):
        if n.identity == 0:
            return n.valence
        return np.clip(n.valence + self.p["identity_valence"] * n.identity * n.lean
                       * self.pop.ideology[idx], -1, 1)

    def _impact(self, n, idx, sign=1.0, v=None):
        if not n.about_product or idx.size == 0:
            return
        p = self.p
        v = self._valence(n, idx) if v is None else v
        neg = 1 + p["negativity_bias"] * (np.asarray(v) < 0)
        delta = sign * p["opinion_impact"] * v * (0.5 + 0.5 * n.credibility) * neg \
            * (0.5 + self.pop.reactivity[idx])
        o = np.clip(self.opinion[idx], -0.995, 0.995)
        self.opinion[idx] = np.tanh(np.arctanh(o) + delta)

    def _seed(self, n):
        s, rng, pop = n.seed, self.rng, self.pop
        count = int(s["share"] * pop.n) if "share" in s else int(s.get("count", 0))
        if count <= 0:
            return
        target = s.get("target", "random")
        if target == "influencers":
            idx = self.net.influencers[:count]
        elif target.startswith("segment:"):
            name = target.split(":", 1)[1]
            if name not in pop.segment_names:
                name = pop.segment_names[0]
            pool = np.flatnonzero(pop.segment == pop.segment_names.index(name))
            idx = rng.choice(pool, min(count, pool.size), replace=False)
        elif target in ("active", "lean_plus", "lean_minus"):
            score = pop.expressiveness.copy()
            if target != "active":   # activists on one pole of the cultural axis
                score *= np.clip(pop.ideology * (1 if target == "lean_plus" else -1), 0, None)
            pool = np.argsort(-score)[: max(count * 20, 1000)]
            idx = rng.choice(pool, min(count, pool.size), replace=False)
        else:
            idx = rng.choice(pop.n, min(count, pop.n), replace=False)
        idx = idx[self.state[n.idx, idx] == UNAWARE]
        self.state[n.idx, idx] = SPREADER
        if self.tracker:
            self.tracker.seeded(n.idx, idx)
        if n.about_product:
            self.product_aware[idx] = True
        self._impact(n, idx)
        self.log("release", f"Now circulating: {n.label}.", n.id)

    def _encounter(self, n, idx, sp, t):
        p, pop, rng, k = self.p, self.pop, self.rng, n.idx
        logit = (p["accept_bias"] + p["w_credibility"] * (2 * n.credibility - 1)
                 - p["w_skepticism"] * pop.skepticism[idx] * (1 - n.credibility)
                 + p["w_confirmation"] * self.opinion[idx] * n.valence
                 + p["w_social_proof"] * sp[idx]
                 + p["w_emotion_belief"] * n.emotionality * (pop.reactivity[idx] - 0.3))
        if n.identity:
            logit = logit + p["w_identity"] * n.identity * n.lean * pop.ideology[idx]
        if n.source == "brand":
            logit = logit + p["w_trust"] * (2 * pop.trust_brand[idx] - 1)
        elif n.source == "media":
            logit = logit + p["w_trust"] * (2 * pop.trust_media[idx] - 1)
        for d in self.debunkers[k]:
            if t >= d.start:
                st = self.state[d.idx, idx]
                logit = logit - p["w_prior_debunk"] * d.credibility * ((st == SPREADER) | (st == BELIEVER))
        acc = rng.random(idx.size) < sigmoid(logit)
        a_idx, r_idx = idx[acc], idx[~acc]
        v = self._valence(n, a_idx)
        outrage = 1 + 0.5 * (np.asarray(v) < 0)
        self.arousal[a_idx] = np.minimum(1.0, self.arousal[a_idx] + p["arousal_gain"] * n.emotionality
                                         * pop.reactivity[a_idx] * (0.5 + np.abs(v)) * outrage)
        share = sigmoid(p["share_bias"] + p["w_emotion"] * n.emotionality
                        + p["w_arousal"] * self.arousal[a_idx]
                        + p["w_expressive"] * pop.expressiveness[a_idx]) * (0.3 + 0.7 * n.novelty(t))
        spread = rng.random(a_idx.size) < share
        self.state[k, a_idx[spread]] = SPREADER
        self.state[k, a_idx[~spread]] = BELIEVER
        self.state[k, r_idx] = REJECTER
        if n.about_product:
            self.product_aware[idx] = True
        self._impact(n, a_idx, v=v)
        if n.debunk_target is not None:
            self._correct(n, a_idx)
            target = self.narr[n.debunk_target]
            new = idx[self.state[target.idx, idx] == UNAWARE]
            new = new[rng.random(new.size) < p["streisand"]]
            if new.size:
                if self.tracker:
                    self.tracker.via_debunk(target.idx, new)
                self._encounter(target, new, self._zeros, t)

    def _correct(self, d, idx):
        target = self.narr[d.debunk_target]
        st = self.state[target.idx, idx]
        cand = idx[(st == SPREADER) | (st == BELIEVER)]
        if cand.size == 0:
            return
        prob = self.p["correction_efficacy"] * d.credibility * (0.5 + 0.5 * self.pop.skepticism[cand])
        flip = cand[self.rng.random(cand.size) < prob]
        self.state[target.idx, flip] = REJECTER
        self._impact(target, flip, sign=-(1 - self.p["continued_influence"]))
        target.corrected += flip.size

    # ---------------------------------------------------------------- main loop
    def step(self):
        t, p, pop, rng, net, K = self.t, self.p, self.pop, self.rng, self.net, self.K
        N = pop.n
        for n in self.narr:
            if n.start == t:
                self._seed(n)
        attn = float(self.attn[min(t, len(self.attn) - 1)])
        hour_local = (self.start_hour + t + pop.tz) % 24
        online = rng.random(N, dtype=np.float32) < pop.activity * DIURNAL[hour_local]
        active = [n for n in self.narr if t >= n.start]

        X = self.X
        X.fill(0)
        any_post = np.zeros(N, bool)
        posts, believers = {}, {}
        for n in active:
            st = self.state[n.idx]
            bel = (st == SPREADER) | (st == BELIEVER)
            X[:, K + n.idx] = bel
            believers[n.idx] = int(bel.sum())
            si = np.flatnonzero((st == SPREADER) & online)
            pp = (p["post_rate"] * (0.5 + 3 * pop.expressiveness[si]) * (1 + self.arousal[si])
                  * (0.3 + 0.7 * n.novelty(t)) * (0.5 + n.emotionality))
            posted = si[rng.random(si.size) < pp]
            X[posted, n.idx] = 1
            any_post[posted] = True
            if n.truth is False or n.valence < -0.2:
                self.posted_neg_ever[posted] = True
            if self.tracker:
                self.tracker.posted(t, n.idx, posted)
            posts[n.idx] = posted.size
            if self._notable_logged[n.idx] < 2 and posted.size:
                for i in posted[np.isin(posted, list(self.notable))][:1]:
                    self._notable_logged[n.idx] += 1
                    self.log("influencer", f"One of the most-followed accounts ({self.notable[int(i)]:,} "
                                           f"followers) posts about {n.label}.", n.id)
        self.posted_ever |= any_post
        X[:, 2 * K] = self.opinion * any_post
        X[:, 2 * K + 1] = any_post
        X[:, 2 * K + 2] = self.adopted

        Y = net.W @ X

        for n in active:
            pu = n.pickup
            if pu and n.picked_up_at is None and believers[n.idx] / N >= float(pu.get("threshold", 0.02)):
                s = t + int(pu.get("delay", 2))
                n.media.append((s, s + int(pu.get("duration", 24)), float(pu.get("intensity", 0.03))))
                n.picked_up_at = t
                self.log("media", f"Mainstream media picks up {n.label}.", n.id)

        for n in active:
            k = n.idx
            feed = self.feed[k]
            feed *= p["feed_decay"]
            feed += Y[:, k]
            sp = Y[:, K + k] / net.instr_safe
            un = np.flatnonzero(self.state[k] == UNAWARE)
            if un.size == 0:
                continue
            on = online[un]
            p_net = 1 - np.exp(-p["feed_visibility"] * feed[un])
            p_trend = min(p["trend_cap"], p["algo_boost"] * posts[k] / N)
            p_media = n.media_intensity(t) * pop.media_reach[un]
            p_seen = attn * (1 - (1 - p_net * on) * (1 - p_trend * on) * (1 - p_media))
            seen = un[rng.random(un.size) < p_seen]
            if seen.size:
                self._encounter(n, seen, sp, t)

        for n in active:
            k, st = n.idx, self.state[n.idx]
            si = np.flatnonzero(st == SPREADER)
            if si.size:
                sp = Y[si, K + k] / net.instr_safe[si]
                stop = p["forget_rate"] + p["stifle_rate"] * sp + 0.05 * (1 - n.novelty(t)) + 0.05 * (1 - attn)
                st[si[rng.random(si.size) < stop]] = BELIEVER
            if p["repetition_effect"] > 0:
                ri = np.flatnonzero((st == REJECTER) & online & (self.feed[k] > 0))
                if ri.size:
                    pr = p["repetition_effect"] * (1 - np.exp(-p["feed_visibility"] * self.feed[k, ri])) \
                        * (1 - pop.skepticism[ri])
                    flip = ri[rng.random(ri.size) < pr]
                    st[flip] = BELIEVER
                    self._impact(n, flip)
            self.feed[k, online] = 0

        hear = np.flatnonzero(online & (Y[:, 2 * K + 1] > 0))
        if hear.size:
            m = Y[hear, 2 * K] / Y[hear, 2 * K + 1]
            o = self.opinion[hear]
            diff = m - o
            eps = p["confidence_bound"] * (0.5 + pop.openness[hear])
            self.opinion[hear] = o + p["social_influence"] * (0.5 + pop.conformity[hear]) \
                * diff * np.exp(-(diff / eps) ** 2)
        self.opinion += p["opinion_relax"] * (pop.opinion0 - self.opinion)
        self.arousal *= p["arousal_decay"]

        # buying
        new_adopt = 0
        ci = np.flatnonzero(pop.can_adopt & ~self.adopted & ~self.churned & self.product_aware)
        if ci.size:
            att = sigmoid(p["a_opinion"] * self.opinion[ci] + p["a_need"] * (2 * pop.need[ci] - 1)
                          - p["a_price"] * (2 * pop.price_sensitivity[ci] - 1)
                          + p["a_peer"] * Y[ci, 2 * K + 2] / net.instr_safe[ci]
                          + p["a_innov"] * (2 * pop.novelty[ci] - 1) + p["a_bias"])
            haz = p["adopt_base_rate"] * att * (0.3 + 0.7 * online[ci])
            new = ci[rng.random(ci.size) < haz]
            self.adopted[new] = True
            self.adopt_time[new] = t
            new_adopt = new.size
        # leaving: hostile, aroused customers cancel / switch / withdraw
        new_churn = 0
        cu = np.flatnonzero(self.adopted & pop.can_adopt & self.product_aware)
        if cu.size and p["churn_rate"] > 0:
            haz = p["churn_rate"] * sigmoid(-(self.opinion[cu] - p["churn_threshold"]) * 6) \
                * (1 + 2 * self.arousal[cu]) * (0.3 + 0.7 * online[cu])
            gone = cu[rng.random(cu.size) < haz]
            self.adopted[gone] = False
            self.churned[gone] = True
            new_churn = gone.size
        # product experience -> reviews; defects -> incident posts (micro events)
        if self.quality is not None:
            ex = np.flatnonzero(self.adopt_time == t - int(p["experience_delay"]))
            if ex.size:
                o = np.clip(self.opinion[ex], -0.995, 0.995)
                self.opinion[ex] = np.tanh(np.arctanh(o) + p["experience_impact"] * float(self.quality))
                r = ex[rng.random(ex.size) < p["review_rate"] + pop.expressiveness[ex]]
                if self.tracker:
                    self.tracker.own(self.review.idx, r[self.state[self.review.idx, r] == UNAWARE])
                self.state[self.review.idx, r] = SPREADER
        if self.incident is not None and t < p["defect_stop_hour"]:
            users = np.flatnonzero(self.adopted & (self.adopt_time >= 0) & (self.adopt_time <= t - 12))
            hit = users[rng.random(users.size) < p["defect_rate"] / 24]
            hit = hit[self.state[self.incident.idx, hit] == UNAWARE]
            if hit.size:
                if self.incidents == 0:
                    self.log("incident", "First buyer posts about a product failure.", self.incident.id)
                self.incidents += hit.size
                self.state[self.incident.idx, hit] = SPREADER
                if self.tracker:
                    self.tracker.own(self.incident.idx, hit)
                self.product_aware[hit] = True
                self._impact(self.incident, hit)
                self.arousal[hit] = 1.0

        self._record(t, online, posts, new_adopt, new_churn, attn)
        if self.snap and t % self.snap["every"] == 0:
            self._snapshot(t)
        if self.tracker:
            self.tracker.end_hour(self, t)
        self.t += 1

    def _snapshot(self, t):
        s, idx = self.snap, self.snap["idx"]
        rumor = [n.idx for n in self.narr if n.truth is False or n.valence < -0.3]
        spreading = np.zeros(idx.size, bool)
        hostile_spread = np.zeros(idx.size, bool)
        for n in self.narr:
            sp = self.state[n.idx, idx] == SPREADER
            spreading |= sp
            if n.idx in rumor:
                hostile_spread |= sp
        flags = (self.product_aware[idx].astype(np.uint8) | (spreading << 1) | (hostile_spread << 2)
                 | (self.adopted[idx] & (self.adopt_time[idx] >= 0)) << 3 | self.churned[idx] << 4)
        s["opinion"].append(np.round(np.clip(self.opinion[idx], -1, 1) * 127).astype(np.int8))
        s["flags"].append(flags.astype(np.uint8))
        s["hours"].append(t)

    # ---------------------------------------------------------------- metrics
    def _record(self, t, online, posts, new_adopt, new_churn, attn):
        pop, N, o = self.pop, self.pop.n, self.opinion
        rec = {"hour": t, "online_share": float(online.mean()), "attention": attn}
        rel = sum(posts.get(n.idx, 0) for n in self.narr if n.about_product)
        rec["posts_total"] = sum(posts.values())
        rec["net_sentiment_posts"] = (sum(posts.get(n.idx, 0) * n.valence for n in self.narr
                                          if n.about_product) / rel) if rel else 0.0
        for n in self.narr:
            c = np.bincount(self.state[n.idx], minlength=4)
            aware = (N - c[0]) / N
            rec[f"aware_{n.id}"] = aware
            rec[f"believe_{n.id}"] = (c[1] + c[2]) / N
            rec[f"spreading_{n.id}"] = c[1] / N
            rec[f"posts_{n.id}"] = posts.get(n.idx, 0)
            rec[f"media_{n.id}"] = n.media_intensity(t)
            if self.debunkers[n.idx]:
                rec[f"corrected_{n.id}"] = n.corrected / N
            for i, th in enumerate((0.01, 0.1, 0.25, 0.5)):
                if aware >= th and self._milestones[n.idx] <= i:
                    self._milestones[n.idx] = i + 1
                    self.log("milestone", f"{int(th * 100)}% of people have now heard {n.label}.", n.id)
        # the conversation "turns" only if the new tone holds for 6 straight hours
        sign = int(np.sign(rec["net_sentiment_posts"])) if rel > 30 else 0
        if sign and sign != self._last_net_sign:
            self._turn_run = self._turn_run + 1 if sign == self._turn_sign else 1
            self._turn_sign = sign
            if self._turn_run >= 6:
                if self._last_net_sign:
                    self.log("turn", "The conversation turns " + ("positive." if sign > 0 else "negative."))
                self._last_net_sign = sign
        elif sign:
            self._turn_run = 0
        rec["mean_opinion"] = float(o.mean())
        rec["positive_share"] = float((o > 0.2).mean())
        rec["negative_share"] = float((o < -0.2).mean())
        rec["hostile_share"] = float((o < -0.5).mean())
        rec["polarization"] = float(o.std())
        rec["buzz"] = float(self.arousal.mean())
        rec["product_awareness"] = float(self.product_aware.mean())
        new_buyers = self.adopted & (self.adopt_time >= 0)
        rec["adoption"] = float(new_buyers.sum() / self.n_eligible)
        rec["new_adopters"] = new_adopt
        rec["churn"] = float(self.churned.sum() / max(self.n_customers, 1)) if self.n_customers else 0.0
        rec["churned_total"] = int(self.churned.sum())
        rec["new_churn"] = new_churn
        rec["incidents"] = self.incidents
        S = len(self.seg_n)
        seg_o = np.bincount(pop.segment, weights=o, minlength=S) / self.seg_n
        seg_aw = np.bincount(pop.segment, weights=self.product_aware, minlength=S) / self.seg_n
        seg_a = np.bincount(pop.segment, weights=new_buyers, minlength=S)
        seg_c = np.bincount(pop.segment, weights=self.churned, minlength=S)
        for i, name in enumerate(pop.segment_names):
            rec[f"opinion_{name}"] = float(seg_o[i])
            rec[f"aware_seg_{name}"] = float(seg_aw[i])
            if self.seg_eligible[i]:
                rec[f"adoption_{name}"] = float(seg_a[i] / self.seg_eligible[i])
            if self.seg_customers[i]:
                rec[f"churn_{name}"] = float(seg_c[i] / self.seg_customers[i])
        self.history.append(rec)

    def history_arrays(self):
        keys = self.history[0].keys()
        return {k: np.array([h.get(k, 0.0) for h in self.history], float) for k in keys}
