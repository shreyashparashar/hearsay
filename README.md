---
title: Hearsay
emoji: 📣
colorFrom: yellow
colorTo: pink
sdk: docker
app_port: 7860
pinned: false
---

# Hearsay

Rehearse how the public will react before it happens. Type a launch, a headline, a government policy
or programme, a price change or a rumour, drop in product photos or the ad, and Hearsay simulates up to
a million people hearing it, believing or doubting it, arguing about it, taking it up and walking away,
hour by hour. Then it answers in plain words: should you go ahead, what did each group think, who did
what, which alternatives it tested and which worked best, and the step-by-step plan to follow.

While it runs you watch a real slice of the simulated society (whole friend circles from every group
plus the most-followed accounts) pass the stories along, person to person: every pulse is someone
telling someone, every gold line is word of mouth that actually happened in the simulation, and the
side panel shows what they're posting.

Free to run: Python, a free AI model (or none), and free hosting on Hugging Face Spaces.

## How it works

```
your text + images ──► AI reader ──► event spec (editable dials, audience, likely stories)
                                          │
             memory of 205 real events ───┤  analogs, patterns, timing priors
                                          ▼
                                    composer  ──► full scenario: people, network, stories,
                                          │       your response, economy, news cycle
                                          ▼
                     agent simulation (up to 1M people, hourly) ──► narrator ──► dashboard
```

1. **Reading.** A free vision/language model (Gemini's free tier by default; Ollama, OpenRouter or
   Groq also work) reads your words and images and fills in an event spec: what kind of event it is,
   how it reflects on the brand, emotional charge, identity charge, harm, blame, hype, price, who the
   audiences are, and which secondary stories (rumors, memes, boycotts, rival jabs) would likely
   emerge. Without a model a keyword reader fills it in roughly. You can edit everything.
2. **Remembering.** The spec is compared with a library of real public reactions (Tylenol 1982,
   New Coke, Note 7, United 3411, Nike/Kaepernick, Bud Light, Netflix twice, SVB, CrowdStrike,
   Cracker Barrel and more). The closest analogs set timing priors; cross-event patterns ("loud
   outrage, little behaviour change", "boycotts bite when switching is easy", "denials repeat the
   claim") nudge the dynamics and are shown to you with their evidence.
3. **Composing.** History's playbook for that kind of event adds the stories that usually emerge on
   their own; your response (apologise, deny, recall, walk back, stand firm, joke...) and its timing
   are added; the world around it is set (economy, news cycle, how divided society is, a bigger
   story breaking, time zones).
4. **Simulating.** Each person has their own traits (skepticism, emotional reactivity, openness,
   conformity, how much they post, when they're online, trust in brand and media, cultural views,
   need, price sensitivity, innovativeness) and state (opinion, arousal, a feed, what they believe,
   whether they bought or left). Every hour, across a social graph of echo-chamber communities and a
   heavy-tailed follow layer with natural influencers, stories spread through feeds, trending and
   media; people accept or reject them, shift opinion, get angry and share, get bored and stop, get
   corrected (partly), and newsrooms pick stories up past a tipping point. Buyers later use the
   product: reviews spread, defects produce incident posts that can escalate into national news;
   hostile customers cancel or withdraw. Micro events (one buyer's video) and macro forces (a war
   eating everyone's attention) play out in the same run.
5. **Explaining.** A verdict, an hour-by-hour timeline (releases, influencer posts, tipping points,
   media pickups, turns in tone), the crowd itself replayed as 4,096 real agents, group-by-group
   cards with what moved each group, voices from individual simulated people, a briefing, and a
   side-by-side with what similar past events did.

## What's in the memory

205 hand-coded public reactions across brands, government policy, economy and markets, geopolitics,
public health, politics, work and labour, and technology, with India well represented (demonetisation,
GST, farm laws, Agnipath, UPI, Maggi, Tanishq, Paytm, the IndiGo cancellations and more), plus 25
cross-event patterns. Add your own in `crowdsim/knowledge/events.yaml`; the format is documented at
the top of the file. Events with a `wiki` entry can have their attention curves measured from real
Wikipedia pageviews with `python tools/learn_attention.py`.

## Tuning for small servers

- `CROWDSIM_OPTION_AGENTS` (default 25000): crowd size used to test each alternative plan.
- `CROWDSIM_OPTION_DAYS` (default 7): days simulated per alternative.
- `CROWDSIM_MAX_AGENTS`: cap on the main crowd.
Untick "Test alternatives" in the app to skip option testing entirely.

## Setup

### 1. Run it on your computer (10 minutes)

You need Python 3.10 or newer.

```bash
git clone https://github.com/<you>/hearsay.git    # or unzip the download
cd hearsay
python -m venv .venv
source .venv/bin/activate                          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn crowdsim.server:app --port 7860
```

Open http://localhost:7860. It works straight away with the keyword reader.

### 2. Give it a free AI model so it understands images and plain language

Pick one.

**Google AI Studio (easiest, free tier, reads images).** Go to https://aistudio.google.com/apikey,
sign in, click *Create API key*, copy it. Then:

```bash
export GEMINI_API_KEY=your-key            # Windows PowerShell: $env:GEMINI_API_KEY="your-key"
uvicorn crowdsim.server:app --port 7860
```

The default model is `gemini-2.5-flash`. Free models get renamed over time; if you see a "model not
found" note in the app, check the model list in AI Studio and set `CROWDSIM_LLM_MODEL` to a current
free Flash model. Each analysis uses about two or three requests, so free daily limits go a long way.

**Ollama (fully local, no account).** Install from https://ollama.com, then:

```bash
ollama pull qwen2.5vl:7b                  # a vision model; needs ~8 GB of RAM or VRAM
export CROWDSIM_USE_OLLAMA=1
uvicorn crowdsim.server:app --port 7860
```

**Any OpenAI-compatible provider** (OpenRouter free models, Groq, others):

```bash
export CROWDSIM_LLM_BASE_URL=https://openrouter.ai/api/v1
export CROWDSIM_LLM_API_KEY=your-key
export CROWDSIM_LLM_MODEL=<a model id from the provider>
export CROWDSIM_VISION_MODEL=<a vision model id>   # only if the main one can't see images
```

All options are in `.env.example`. The status chip at the top of the app shows which reader is active.

### 3. Put it online for free (Hugging Face Spaces)

Spaces gives you a free CPU machine and a public URL. This repo is already a valid Docker Space
(the header at the top of this README is its config).

1. Create an account at https://huggingface.co, then *New Space*. Choose **Docker**, template
   **Blank**, hardware **CPU basic (free)**. Name it, e.g. `hearsay`.
2. In the Space: *Settings → Variables and secrets → New secret*, name `GEMINI_API_KEY`, paste your
   key. (Secrets stay private; never put keys in the code.)
3. Upload the code. Either drag the project files into *Files → Add file → Upload files*, or:

   ```bash
   git remote add space https://huggingface.co/spaces/<you>/hearsay
   git push space main      # use a Hugging Face access token with write permission as the password
   ```

4. Wait for the build (a few minutes). Your dashboard is live at
   `https://huggingface.co/spaces/<you>/hearsay`.

Free Spaces sleep after a period of inactivity and wake on the next visit. Simulations run one at a
time; others wait in a queue shown in the progress bar. If the server is small, cap the crowd with a
`CROWDSIM_MAX_AGENTS` variable (e.g. `500000`).

### 4. Keep GitHub and the Space in sync (optional)

Push the code to a GitHub repo. Then in GitHub: *Settings → Secrets and variables → Actions*:

- secret `HF_TOKEN`: a Hugging Face access token with write permission
- variable `HF_SPACE`: `<you>/hearsay`

Every push to `main` now runs the tests (`test` workflow) and redeploys the Space (`deploy to hugging
face` workflow). The `simulate` workflow still runs big batch simulations from the command line.

### 5. Run it with Docker instead (any host)

```bash
docker build -t hearsay .
docker run -p 7860:7860 -e GEMINI_API_KEY=your-key hearsay
```

The same image runs on Render, Railway, Fly.io or a VPS.

## Make the memory deeper

**Learn real attention curves.** `tools/learn_attention.py` downloads daily Wikipedia pageviews
(free, from July 2015) around each event that has a `wiki:` entry, measures the peak day and how
fast attention decayed, and saves `crowdsim/knowledge/attention_learned.json`. The simulator then
uses measured numbers instead of hand-coded guesses.

```bash
export CROWDSIM_CONTACT=you@example.com     # Wikimedia asks for a contact in the User-Agent
python tools/learn_attention.py
```

**Add events.** Append to `crowdsim/knowledge/events.yaml` in the same format (features, outcome,
response, summary, lessons, optional `wiki`). Events from your own industry make analogs sharper.

**Add or change patterns and playbooks.** `patterns.yaml` holds cross-event rules with conditions and
effects; `archetypes.yaml` holds what typically emerges around each kind of event. Both are plain
YAML.

**Calibrate on your own history.** For forecasting rather than comparing options, fit the model to
a past event of yours with the command-line tools:

```bash
python -m crowdsim calibrate scenarios/my_past_launch.yaml --observed data/observed.csv --trials 60
```

`observed.csv` has an `hour` column plus any metric the model produces (`posts_total` from social
listening, `net_sentiment_posts`, survey awareness as `aware_<story>`...). See
`data/example_observed.csv`.

## Command line (batch runs)

```bash
python -m crowdsim run scenarios/product_launch.yaml --runs 5            # 1M agents, HTML report
python -m crowdsim run scenarios/product_launch.yaml --set narratives.company_denial.start=36 --out outputs/early
python -m crowdsim compare outputs/early outputs/phone_launch_with_rumor
```

## Tests

```bash
python tests/test_smoke.py && python tests/test_app.py
```

They need no network and no key (the AI round-trip is tested against a local fake server).

## Honest limits

- The people are rule-based minds, not language models; the mechanisms (bounded-confidence opinion
  change, rumor spreading and stifling, Bass-style adoption, agenda setting, illusory truth,
  continued influence, Streisand effect, identity-driven belief, outrage sharing) are well studied,
  but their strengths are knobs, not laws.
- The event library's numbers are hand-coded estimates from public reporting, made so events can
  be compared. Treat them as informed priors.
- Uncalibrated results are best for comparing your options ("apologise in 6 hours or 48?"). Tipping
  points make outcomes uncertain: use several runs and read the ranges.
- One opinion dimension per run (toward the brand or organisation at the centre).

## Project layout

```
crowdsim/
  engine.py        the hourly simulation
  population.py    people and their traits
  network.py       the social graph
  knowledge/       events.yaml, archetypes.yaml, patterns.yaml (+ attention_learned.json)
  knowledge.py     analogs, patterns, priors
  interpret.py     AI reader (any OpenAI-compatible endpoint) + keyword fallback
  composer.py      spec + settings + history -> scenario
  narrate.py       verdict, timeline, groups, voices, briefing
  service.py       background simulation jobs
  server.py        FastAPI app and API
  __main__.py      command line: run, compare, calibrate
web/               the dashboard (plain HTML, CSS, JS)
tools/             learn_attention.py
scenarios/         example YAML scenarios for the command line
```
