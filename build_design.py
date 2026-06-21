#!/usr/bin/env python3
"""
build_design.py — take the custom JARVIS UI design bundle and wire it to the
live backend, then emit it as the served page (web/dist/index.html).

The design (a self-contained dc-runtime + Three.js bundle) ships with demo data
only. We keep its EXACT markup/look and surgically rewire the embedded component
to use live data: /api/news, /api/techfeed, /api/vitals, the /ws socket, and
browser voice. Re-run this whenever the source design or wiring changes.
"""
import json
import re
import shutil
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "web" / "design-src.html"
OUT = Path(__file__).resolve().parent / "web" / "dist" / "index.html"

# ---- the live-backend connector injected into the design component ----
CONNECTOR = r'''
  _connectBackend() {
    this._realLog("[CORE]", "uplink established", "#a855f7", "#7a6a9c");
    const pull = () => fetch("/api/vitals").then(r => r.json()).then(v => {
      this.setState({ vitals: [
        { label: "NEURAL LOAD", read: Math.round(v.cpu) + "%", pct: Math.min(96, Math.max(4, v.cpu)) + "%", color: v.cpu > 82 ? "#e879f9" : "#a855f7" },
        { label: "MEMORY", read: v.mem_used_gb.toFixed(1) + "GB", pct: Math.min(96, v.mem_pct) + "%", color: "#c084fc" },
        { label: "DISK", read: Math.round(v.disk_free_gb) + "GB", pct: Math.min(96, v.disk_pct) + "%", color: "#a855f7" },
        { label: "NETWORK", read: Math.round(v.net_down_kbs) + "Kb", pct: Math.min(96, Math.max(4, v.net_down_kbs / 12)) + "%", color: "#d8b4fe" },
      ] });
    }).catch(() => {});
    pull(); this._iv.push(setInterval(pull, 2500));

    fetch("/api/news").then(r => r.json()).then(d => {
      if (d.markets && d.markets.length) this._markets = d.markets.map(m => ({ nm: m.name, v: Math.abs(m.change_pct).toFixed(1) + "%", up: m.change_pct >= 0, col: m.change_pct >= 0 ? "#34e7b3" : "#ff7a9c", arr: m.change_pct >= 0 ? "▲ " : "▼ " }));
      if (d.world && d.world.length) this._headlines = d.world.slice(0, 5).map(n => ({ h: n.title, src: (n.source || "").toUpperCase(), t: "" }));
      if (d.war && d.war.length) this._alerts = d.war.slice(0, 3).map(w => ({ txt: w.title }));
      if (d.briefing) this._worldBrief = d.briefing;
      this.forceUpdate();
    }).catch(() => {});

    fetch("/api/techfeed").then(r => r.json()).then(d => {
      const items = [].concat(d.hackernews || [], d.reddit || [], d.arxiv || [], d.youtube || []);
      if (items.length) this._techItems = items.slice(0, 8).map(it => ({ h: it.title, src: (it.source || "").toUpperCase(), score: String(it.score || ""), t: "" }));
      if (d.digest) this._techFeature = { kicker: "AI TODAY", h: (d.hackernews && d.hackernews[0] ? d.hackernews[0].title : "Today in AI"), desc: d.digest, src: "HACKER NEWS · REDDIT · ARXIV" };
      this.forceUpdate();
    }).catch(() => {});

    try {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(proto + "://" + location.host + "/ws"); this._ws = ws;
      ws.onmessage = (e) => {
        let m; try { m = JSON.parse(e.data); } catch (x) { return; }
        if (m.type === "reply") {
          if (m.text && m.text.indexOf("uplink is down") !== -1) {
            this._realLog("[SYS]", "groq unreachable — using free Gemini", "#9d7bff", "#7a6a9c");
            this._geminiFallback(this.state.lastYou || "Hello").then((g) => { const out = g || m.text; this.setState({ lastJarvis: out, mode: "speaking" }); this._spike = 1; this._speak(out); this._realLog("[VOICE]", "speaking: " + out.slice(0, 70), "#c084fc", "#a78bce"); });
          } else { this.setState({ lastJarvis: m.text, mode: "speaking" }); this._spike = 1; this._speak(m.text); this._realLog("[VOICE]", "speaking: " + m.text.slice(0, 70), "#c084fc", "#a78bce"); }
        }
        else if (m.type === "tool") { this._realLog("[ACT]", m.name + "(" + Object.entries(m.args || {}).map(kv => kv[0] + "=" + kv[1]).join(", ") + ")", "#e879f9", "#c98fd6"); }
        else if (m.type === "tool_result") { this._realLog("[ACT]", m.name + " → " + String(m.result).slice(0, 64), "#e879f9", "#c98fd6"); }
        else if (m.type === "status" && m.state === "thinking") { this.setState({ mode: "thinking" }); this._realLog("[CORE]", "processing request", "#a855f7", "#7a6a9c"); }
      };
      ws.onclose = () => this._realLog("[SYS]", "uplink dropped", "#9d7bff", "#7a6a9c");
    } catch (x) {}
  }

  _puterReady() {
    if (window.puter) return Promise.resolve();
    if (this._puterP) return this._puterP;
    this._puterP = new Promise((res) => { const s = document.createElement("script"); s.src = "https://js.puter.com/v2/"; s.onload = () => res(); s.onerror = () => res(); document.head.appendChild(s); });
    return this._puterP;
  }

  async _geminiFallback(prompt) {
    try {
      await this._puterReady();
      if (!window.puter || !window.puter.ai) return null;
      const r = await window.puter.ai.chat("You are JARVIS, a concise, witty British AI butler. Answer in one or two short sentences and address the user as sir. " + prompt, { model: "gemini-3.5-flash" });
      return (r && r.message && r.message.content) || (r && r.text) || (typeof r === "string" ? r : null);
    } catch (e) { return null; }
  }

  _realLog(tag, text, tc, xc) {
    this.setState((s) => { const logs = [...s.logs, { tag, text, tagColor: tc, textColor: xc }]; if (logs.length > 60) logs.shift(); return { logs }; });
  }

  _speak(t) {
    try {
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(t); u.rate = 1.03; u.pitch = 0.92;
      const vs = window.speechSynthesis.getVoices().filter(v => v.lang && v.lang.startsWith("en"));
      const pick = vs.find(v => /daniel|arthur|enhanced|google uk english male/i.test(v.name)) || vs[0];
      if (pick) u.voice = pick;
      u.onend = () => { this.setState({ mode: this.state.talking ? "listening" : "idle" }); if (this.state.talking) setTimeout(() => this._listen(), 280); };
      window.speechSynthesis.speak(u);
    } catch (x) {}
  }

  _listen() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR || this._rec) return;
    const r = new SR(); r.lang = "en-US"; r.interimResults = false; r.continuous = false;
    r.onresult = (e) => {
      const text = e.results[e.results.length - 1][0].transcript.trim(); if (!text) return;
      this.setState({ lastYou: text }); this._realLog("[STT]", 'heard: "' + text + '"', "#34e7b3", "#9fe9d2");
      const t = text.toLowerCase();
      if (/\b(news|world|headlines?|market|economy)\b/.test(t)) this._go("world");
      else if (/\b(tech|technology|reddit|arxiv|hacker|papers?)\b/.test(t)) this._go("tech");
      else if (/\b(reactor|system|arc)\b/.test(t)) this._go("system");
      else if (/\b(core|home|standby)\b/.test(t)) this._go("core");
      if (this._ws && this._ws.readyState === 1) this._ws.send(JSON.stringify({ type: "command", text }));
    };
    r.onend = () => { this._rec = null; if (this.state.talking && !window.speechSynthesis.speaking) setTimeout(() => this._listen(), 320); };
    r.onerror = () => { this._rec = null; };
    this._rec = r; try { r.start(); } catch (x) {}
  }

  renderVals() {'''

# ---- exact source fragments to replace (from the design component) ----
DEMO_BLOCK = (
    '    this._iv.push(setInterval(() => this._pushLog(), 1700));\n'
    '    this._iv.push(setInterval(() => this._tickVitals(), 2200));\n'
    '    this._iv.push(setInterval(() => { if ((this.props.coreState ?? "auto") === "auto" && !this.state.talking) this._cycleMode(); }, 6500));\n'
    '    for (let i = 0; i < 12; i++) this._pushLog(true);'
)
DEMO_REPLACE = '    this._connectBackend();'

ONTALK_OLD = (
    '  _onTalk = () => {\n'
    '    const next = !this.state.talking;\n'
    '    this.setState({ talking: next, mode: next ? "listening" : "idle", lastYou: next ? "" : this.state.lastYou, lastJarvis: next ? "Listening, sir. Go ahead." : "Session ended. Standing by." });\n'
    '  };'
)
ONTALK_NEW = (
    '  _onTalk = () => {\n'
    '    const next = !this.state.talking;\n'
    '    this.setState({ talking: next, mode: next ? "listening" : "idle", lastYou: next ? "" : this.state.lastYou, lastJarvis: next ? "Listening, sir. Go ahead." : "Session ended. Standing by." });\n'
    '    if (next) { this._spike = 1; this._listen(); } else { try { this._rec && this._rec.stop(); } catch (x) {} this._rec = null; window.speechSynthesis.cancel(); }\n'
    '  };'
)


# ---- wire the SYSTEM section's reactor to the real CC-BY .glb model ----
# Surgical hooks into the existing _initReactor: load the GLB into the same
# rotating group (so spin/drag work for free), swap its built-in assembled /
# unassembled states on explode, and hide the procedural reactor on success.
# If the model or loader is missing, the procedural reactor stays as fallback.
REACTOR_GROUP_OLD = '    const reactor = new THREE.Group(); reactor.scale.setScalar(0.78); scene.add(reactor);'
REACTOR_GROUP_NEW = REACTOR_GROUP_OLD + "\n" + (
    '    let _asm = null, _unasm = null;\n'
    '    const _frame = (m) => { const b = new THREE.Box3().setFromObject(m); const sz = new THREE.Vector3(); b.getSize(sz); const ct = new THREE.Vector3(); b.getCenter(ct); const k = 3.4 / Math.max(sz.x, sz.y, sz.z || 1); m.scale.setScalar(k); m.position.set(-ct.x * k, -ct.y * k, -ct.z * k); };\n'
    '    const _loadGLB = () => { try { new THREE.GLTFLoader().load("/models/arc-reactor.glb", (g) => { const model = g.scene; model.traverse((o) => { if (o.name === "arc reactor assembled") _asm = o; if (o.name === "arc reactor unassembled") _unasm = o; }); model.children.slice().forEach((c) => { if (c !== _asm && c !== _unasm) c.visible = false; }); if (_asm) _asm.visible = true; if (_unasm) _unasm.visible = false; _frame(_asm || model); reactor.add(model); try { layers.forEach((l) => { l.visible = false; }); core.visible = false; } catch (e) {} }, undefined, () => {}); } catch (e) {} };\n'
    '    if (window.THREE.GLTFLoader) _loadGLB(); else { const _s = document.createElement("script"); _s.src = "/gltfloader.js"; _s.onload = _loadGLB; document.head.appendChild(_s); }'
)
REACTOR_ANIM_OLD = '      reactor.rotation.y = rotY; reactor.rotation.x = rotX;'
REACTOR_ANIM_NEW = REACTOR_ANIM_OLD + '\n      if (_asm && _unasm) { _asm.visible = !exploded; _unasm.visible = exploded; }'

EDITS = [
    (DEMO_BLOCK, DEMO_REPLACE, "demo-interval block"),
    (ONTALK_OLD, ONTALK_NEW, "_onTalk"),
    ("  renderVals() {", CONNECTOR, "connector insert"),
]

# Performance reductions applied everywhere they occur (no count assertion):
# lighter render resolution + fewer particles/points keep the HUD smooth.
REPLACE_ALL = [
    ("Math.min(devicePixelRatio, 1.75)", "Math.min(devicePixelRatio, 1.25)"),
    ("Math.min(devicePixelRatio || 1, 2)", "Math.min(devicePixelRatio || 1, 1.25)"),
    ("for (let i = 0; i < 84; i++)", "for (let i = 0; i < 40; i++)"),   # core particles
    ("for (let i = 0; i < 46; i++)", "for (let i = 0; i < 24; i++)"),   # tech net nodes
    ("for (let i = 0; i < 150; i++)", "for (let i = 0; i < 80; i++)"),  # globe points
]


def main():
    html = SRC.read_text(encoding="utf-8")
    m = re.search(r'(<script type="__bundler/template">)(.*?)(</script>)', html, re.DOTALL)
    if not m:
        sys.exit("FAIL: template script not found")
    # Edit the JSON-encoded template string IN PLACE so every byte except our
    # three edits is identical to the working original (re-serializing the whole
    # template subtly changes asset encodings and breaks the bundler).
    raw = m.group(2)
    for old, new, label in EDITS:
        old_enc = json.dumps(old)[1:-1]      # JSON-escaped form, no surrounding quotes
        new_enc = json.dumps(new)[1:-1]
        n = raw.count(old_enc)
        if n != 1:
            sys.exit(f"FAIL: expected exactly 1 occurrence of {label}, found {n}")
        raw = raw.replace(old_enc, new_enc)
    for old, new in REPLACE_ALL:             # perf tweaks, all occurrences
        raw = raw.replace(json.dumps(old)[1:-1], json.dumps(new)[1:-1])
    json.loads(raw)                          # sanity: still valid JSON
    new_block = m.group(1) + raw + m.group(3)
    html = html[:m.start()] + new_block + html[m.end():]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"OK wrote {OUT} ({len(html)} bytes)")

    # (The heavy 367k-tri .glb was dropped for performance — SYSTEM uses the
    # lightweight procedural reactor. The model stays in web/static/ if we ever
    # want to re-add an optimized/decimated version.)
    stale = [OUT.parent / "models" / "arc-reactor.glb", OUT.parent / "gltfloader.js"]
    for p in stale:
        if p.exists():
            p.unlink()
            print(f"   - removed stale {p.name}")


if __name__ == "__main__":
    main()
