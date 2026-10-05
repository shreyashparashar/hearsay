"""Follows a real slice of the simulated society hour by hour, for the live network view.

Nothing here is decorative. The slice is a set of whole friend circles (communities) from every
audience group plus the most-followed accounts; its ties are the real ties of the simulation.
Every hour it records, from the engine's own state:

  posts   which people in the slice posted which story this hour
  hears   who heard a story for the first time, from whom, and through which channel:
            0 a friend or followed account inside the slice (source = that person)
            1 a friend or followed account outside the slice
            2 the trending feed            3 news media
            4 started it (seeded)          5 heard about the claim through a denial of it
            6 their own experience (bought it, used it, posted a review or a complaint)
          and whether they believed it (1) or rejected it (0)
  op      everyone's attitude (-127..127)
  fl      flags: 1 heard about it, 2 spreading something, 4 spreading something hostile,
          8 bought / took it up, 16 walked away

Attribution follows the engine's exposure model: a newly reached person is credited to the
in-network contacts who posted that story in the last few hours, weighted by tie strength and
by how much those posts have decayed in the feed; if none posted, to the media if the story was on
air that hour, otherwise to the trending feed.
"""
import base64

import numpy as np

from .engine import BELIEVER, REJECTER, SPREADER, UNAWARE

WINDOW = 8          # hours a post can still be sitting unread in someone's feed
MAX_POSTS = 120     # per story per hour, keeps frames small at the peak
MAX_HEARS = 400


def _b64(a):
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode()


class Tracker:
    def __init__(self, pop, net, narr, rng, target=1100, n_hubs=30, on_frame=None):
        self.pop, self.net, self.narr = pop, net, narr
        self.rng = rng
        self.on_frame = on_frame
        N = pop.n
        comm = net.community
        sizes = np.bincount(comm)
        S = len(pop.segment_names)
        seg_share = np.bincount(pop.segment, minlength=S) / N
        # each community belongs to the audience group most of its members are in
        mix = np.bincount(comm.astype(np.int64) * S + pop.segment, minlength=sizes.size * S).reshape(-1, S)
        comm_seg = mix.argmax(axis=1)
        purity = mix.max(axis=1) / np.maximum(sizes, 1)

        chosen = []
        for s in np.argsort(-seg_share):
            want = max(int(target * seg_share[s]), 60)
            pure = np.flatnonzero((comm_seg == s) & (purity > 0.6) & (sizes >= 25) & (sizes <= 260))
            loose = np.flatnonzero((comm_seg == s) & (sizes > 0) & ~np.isin(np.arange(sizes.size), pure))
            rng.shuffle(pure)
            rng.shuffle(loose)
            cands = np.concatenate([pure, loose[np.argsort(sizes[loose])]])
            got = 0
            for c in cands:
                if got >= want:
                    break
                chosen.append(c)
                got += sizes[c]
        members = np.flatnonzero(np.isin(comm, chosen))
        hubs = net.influencers[:n_hubs]
        idx = np.unique(np.concatenate([members, hubs])).astype(np.int64)
        self.idx = idx
        self.n = n = idx.size
        self.pos = np.full(N, -1, np.int32)
        self.pos[idx] = np.arange(n, dtype=np.int32)
        self.is_hub = np.isin(idx, hubs)

        # ties inside the slice; W[i, j] > 0 means i sees j's posts, so messages travel j -> i
        sub = net.W[idx][:, idx].tocoo()
        listen, speak = sub.row.astype(np.int64), sub.col.astype(np.int64)
        pair = {}
        for a, b in zip(speak.tolist(), listen.tolist()):
            key = (a, b) if a < b else (b, a)
            pair[key] = pair.get(key, 0) | (1 if a < b else 2)
        # m=1: both directions (friends), else one-way: listener follows speaker
        self.ties = []
        for (a, b), d in pair.items():
            if d == 3:
                self.ties.append([a, b, 1])
            elif d == 1:
                self.ties.append([a, b, 0])      # b listens to a
            else:
                self.ties.append([b, a, 0])      # a listens to b

        # everyone whose posts can reach someone in the slice
        W = net.W
        rows = [W.indices[W.indptr[i]:W.indptr[i + 1]] for i in idx]
        self.in_nb = rows
        self.in_w = [W.data[W.indptr[i]:W.indptr[i + 1]] for i in idx]
        U = np.unique(np.concatenate(rows)) if rows else np.zeros(0, np.int64)
        self.umap = np.full(N, -1, np.int32)
        self.umap[U] = np.arange(U.size, dtype=np.int32)
        self.U = U
        K = len(narr)
        self.last_post = np.full((K, max(U.size, 1)), -10_000, np.int32)
        self.prev = np.zeros((K, n), np.int8)
        self._seeded = [set() for _ in range(K)]
        self._via_debunk = [set() for _ in range(K)]
        self._own = [set() for _ in range(K)]
        self._posts = {}
        self.frames = []
        self._layout()

    # ------------------------------------------------------------------ layout
    def _layout(self):
        """Friend circles on a ring ordered by audience group; big accounts in the middle."""
        pop, net, idx, n = self.pop, self.net, self.idx, self.n
        comm = net.community[idx]
        seg = pop.segment[idx]
        circles = [c for c in np.unique(comm[~self.is_hub])]
        circles.sort(key=lambda c: (int(np.bincount(seg[comm == c]).argmax()), c))
        x = np.zeros(n, np.float32)
        y = np.zeros(n, np.float32)
        R = 380.0
        golden = np.pi * (3 - np.sqrt(5))
        for ci, c in enumerate(circles):
            m = np.flatnonzero((comm == c) & ~self.is_hub)
            ang = 2 * np.pi * ci / max(len(circles), 1)
            cx, cy = R * np.cos(ang), R * np.sin(ang)
            r0 = 6.5 * np.sqrt(m.size)
            k = np.arange(m.size)
            rr = r0 * np.sqrt((k + 0.5) / max(m.size, 1))
            x[m] = cx + rr * np.cos(k * golden)
            y[m] = cy + rr * np.sin(k * golden)
        h = np.flatnonzero(self.is_hub)
        for j, i in enumerate(h):
            ang = 2 * np.pi * j / max(h.size, 1)
            x[i] = 110 * np.cos(ang)
            y[i] = 110 * np.sin(ang)
        self.x, self.y = x, y
        self.circle = np.full(n, -1, np.int32)
        for ci, c in enumerate(circles):
            self.circle[(comm == c) & ~self.is_hub] = ci

    def graph(self, describe):
        pop, net, idx = self.pop, self.net, self.idx
        return {
            "n": int(self.n),
            "x": [round(float(v), 1) for v in self.x], "y": [round(float(v), 1) for v in self.y],
            "segment": pop.segment[idx].astype(int).tolist(),
            "circle": self.circle.tolist(),
            "followers": net.followers[idx].astype(int).tolist(),
            "hub": self.is_hub.astype(int).tolist(),
            "id": idx.astype(int).tolist(),
            "who": [describe(pop, int(i)) for i in idx],
            "ties": self.ties,
            "stories": [{"id": nn.id, "label": nn.label, "valence": nn.valence, "truth": nn.truth,
                         "kind": nn.kind, "start": nn.start} for nn in self.narr],
            "segments": pop.segment_names,
        }

    # ------------------------------------------------------------------ hooks from the engine
    def seeded(self, k, gidx):
        p = self.pos[gidx]
        self._seeded[k].update(p[p >= 0].tolist())

    def own(self, k, gidx):
        p = self.pos[gidx]
        self._own[k].update(p[p >= 0].tolist())

    def via_debunk(self, k, gidx):
        p = self.pos[gidx]
        self._via_debunk[k].update(p[p >= 0].tolist())

    def posted(self, t, k, gidx):
        if gidx.size == 0:
            return
        m = self.umap[gidx]
        self.last_post[k, m[m >= 0]] = t
        p = self.pos[gidx]
        p = p[p >= 0]
        if p.size:
            if p.size > MAX_POSTS:
                hubs = p[self.is_hub[p]]
                rest = self.rng.choice(p[~self.is_hub[p]], MAX_POSTS - min(hubs.size, MAX_POSTS), replace=False)
                p = np.concatenate([hubs[:MAX_POSTS], rest])
            self._posts[k] = p

    def end_hour(self, sim, t):
        idx, n = self.idx, self.n
        cur = sim.state[:, idx]
        posts = [[int(i), int(k)] for k, arr in self._posts.items() for i in arr]
        hears = []
        newly = (self.prev == UNAWARE) & (cur != UNAWARE)
        ks, js = np.nonzero(newly)
        if ks.size > MAX_HEARS:
            keep = self.rng.choice(ks.size, MAX_HEARS, replace=False)
            ks, js = ks[keep], js[keep]
        for k, j in zip(ks.tolist(), js.tolist()):
            st = int(cur[k, j])
            acc = 1 if st in (SPREADER, BELIEVER) else 0
            n_ = sim.narr[k]
            src, ch = -1, 2
            if j in self._seeded[k]:
                ch = 4
            elif j in self._via_debunk[k]:
                ch = 5
            elif j in self._own[k]:
                ch = 6
            else:
                nb, w = self.in_nb[j], self.in_w[j]
                lp = self.last_post[k, self.umap[nb]] if nb.size else np.zeros(0, np.int32)
                fresh = (lp >= t - WINDOW) & (lp <= t)
                if fresh.any():
                    wt = w[fresh] * (sim.p["feed_decay"] ** (t - lp[fresh]))
                    pick = nb[fresh][self.rng.choice(fresh.sum(), p=wt / wt.sum())]
                    sp = int(self.pos[pick])
                    src, ch = (sp, 0) if sp >= 0 else (-1, 1)
                elif n_.media_intensity(t) > 0:
                    ch = 3
            hears.append([j, k, src, ch, acc])
        self.prev = cur.copy()
        for s in self._seeded:
            s.clear()
        for s in self._via_debunk + self._own:
            s.clear()
        self._posts = {}

        spreading = np.zeros(n, bool)
        hostile = np.zeros(n, bool)
        for nn in sim.narr:
            sp = cur[nn.idx] == SPREADER
            spreading |= sp
            if nn.truth is False or nn.valence < -0.3:
                hostile |= sp
        fl = (sim.product_aware[idx].astype(np.uint8) | (spreading.astype(np.uint8) << 1)
              | (hostile.astype(np.uint8) << 2)
              | ((sim.adopted[idx] & (sim.adopt_time[idx] >= 0)).astype(np.uint8) << 3)
              | (sim.churned[idx].astype(np.uint8) << 4))
        op = np.round(np.clip(sim.opinion[idx], -1, 1) * 127).astype(np.int8)
        frame = {"h": int(t), "op": _b64(op), "fl": _b64(fl.astype(np.uint8)), "posts": posts, "hears": hears}
        self.frames.append(frame)
        if self.on_frame:
            self.on_frame(frame)
