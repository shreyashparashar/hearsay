"""Run: python tests/test_app.py   (no network, no API key needed)."""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crowdsim.interpret import interpret  # noqa: E402
from crowdsim.service import run_sync  # noqa: E402


def test_pipeline_keyword_reader():
    spec = interpret("Viral video: a VoltX scooter battery catches fire in an apartment, two people injured.")
    assert spec["archetype"] == "safety_defect" and spec["brand"] == "VoltX"
    res = run_sync(spec, {"agents": 20000, "days": 3, "runs": 2, "response": {"type": "recall", "hour": 20}})
    assert res["verdict"]["title"] and res["timeline"] and res["segments"] and res["voices"]
    assert res["analogs"][0]["archetype"] in ("safety_defect", "disaster", "outage")
    assert len(res["series"]["hours"]) == 36
    assert res["decision"]["call"] and res["plain"]["program"] and res["people"]["groups"]
    assert res["options"]["options"][0]["id"] == "plan" and len(res["options"]["options"]) >= 2
    net = res["network"]
    assert net["graph"]["n"] > 200 and len(net["frames"]) == 72 and net["graph"]["ties"]
    assert any(f["hears"] for f in net["frames"]) and set(net["lines"]) >= {s["id"] for s in net["graph"]["stories"]}
    assert any(s["id"] == "your_response" for s in res["stories"])


SPEC = {"title": "Lumo ring launch", "brand": "Lumo", "archetype": "product_launch", "summary": "A smart ring.",
        "features": {"valence": 0.6, "emotionality": 0.5, "hype": 0.7, "prominence": 0.4, "price": 0.5},
        "quality": 0.4, "substitutes": 0.6,
        "audience": [{"name": "fitness fans", "share": 0.2, "baseline_opinion": 0.2, "can_adopt": True},
                     {"name": "general public", "share": 0.8, "baseline_opinion": 0.0, "can_adopt": False}],
        "stories": [{"id": "battery_life_doubts", "label": "battery life doubts", "kind": "ugc", "valence": -0.4,
                     "credibility": 0.6, "emotionality": 0.5, "start_hour": 20}],
        "image_observations": ["A matte black ring on a hand"]}


class Fake(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append(body)
        out = {"choices": [{"message": {"content": "```json\n" + json.dumps(SPEC) + "\n```"}}]}
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def test_model_roundtrip():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ.update(CROWDSIM_LLM_BASE_URL=f"http://127.0.0.1:{srv.server_port}/v1",
                      CROWDSIM_LLM_API_KEY="test", CROWDSIM_LLM_MODEL="fake-model")
    try:
        spec = interpret("We launch the Lumo ring", [(b"\x89PNG fake", "image/png")])
        assert spec["reader"] == "model: fake-model" and spec["brand"] == "Lumo"
        assert spec["features"]["identity"] == 0.0 and spec["audience"][0]["name"] == "fitness fans"
        parts = Fake.seen[-1]["messages"][1]["content"]
        assert any(p["type"] == "image_url" and p["image_url"]["url"].startswith("data:image/png;base64,") for p in parts)
    finally:
        for k in ("CROWDSIM_LLM_BASE_URL", "CROWDSIM_LLM_API_KEY", "CROWDSIM_LLM_MODEL"):
            os.environ.pop(k, None)
        srv.shutdown()


def test_api():
    from fastapi.testclient import TestClient
    from crowdsim.server import app
    c = TestClient(app)
    assert c.get("/api/health").json()["events_in_memory"] >= 200
    lib = c.get("/api/library").json()
    assert "policy" in lib["domains"] and len(lib["archetypes"]) >= 19
    r = c.post("/api/read", data={"text": "The government will introduce a new tax on sugary drinks"}).json()
    assert r["spec"]["archetype"] == "government_policy"
    assert c.post("/api/read", data={"text": ""}).status_code == 400
    r = c.post("/api/read", data={"text": "StreamMax raises its subscription price by 40%"}).json()
    assert r["spec"]["archetype"] == "price_change"
    p = c.post("/api/preview", json={"spec": r["spec"], "settings": {"response": {"type": "reversal", "hour": 30}}}).json()
    assert any(x["id"] == "your_response" for x in p["plan"]) and p["analogs"]
    assert "<title>" in c.get("/").text


if __name__ == "__main__":
    test_pipeline_keyword_reader()
    test_model_roundtrip()
    test_api()
    print("ok")
