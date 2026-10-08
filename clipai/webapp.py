"""Flask light-UI: job list, transcript view + fix queue, Latin word edits,
tier-0/tier-1 suggestion overlay, render trigger.

Run: python -m clipai.webapp  (or run.bat). Binds 127.0.0.1:7860.
Design contract: suggestions are an OVERLAY (diff view, accept/reject) —
nothing mutates word.w without an explicit operator edit (edited=true).
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template_string, request, \
    send_file, url_for

from . import jobs
from .types import Transcript

logger = logging.getLogger("clipai.webapp")

app = Flask(__name__)
_edit_lock = threading.Lock()

INDEX = """<!doctype html><meta charset=utf-8><title>Serbian Clip Studio</title>
<style>body{font:15px/1.5 system-ui;max-width:960px;margin:2em auto;padding:0 1em}
.job{border:1px solid #ccc;border-radius:8px;padding:10px 14px;margin:8px 0}
.queued{color:#888}.running{color:#06c}.transcribed{color:#080}.failed{color:#c00}
a{color:#06c;text-decoration:none}code{background:#f4f4f4;padding:1px 4px}</style>
<h1>Serbian Clip Studio</h1>
<h2>New job</h2>
<form method=post action=/jobs>
Video: <select name=video>{% for v in videos %}<option>{{v}}</option>{% endfor %}</select>
Engine: <select name=engine><option>sr-v3-ct2<option>turbo<option>large-v3</select>
Smart cut: <select name=smart_cut><option>off<option>gentle<option>aggressive</select>
Clips: <input name=num_clips value=5 size=3>
<button>Queue job</button></form>
<p><i>CPU-only box: ASR runs ~3–9× realtime. A 50-min podcast is an overnight-class job — queue it and come back.</i></p>
<h2>Jobs</h2>
{% for j in jobs %}
<div class=job><a href=/jobs/{{j.id}}><code>{{j.id}}</code></a>
<b class={{j.state}}>{{j.state}}</b> {{j.video.split('\\\\')[-1].split('/')[-1]}}
— stage: {{j.stage or '—'}}
{% if j.progress is not none and j.state == 'running' %}
 — {{(j.progress*100)|round}}%{% if j.asr_frac %} of audio{% endif %}{% endif %}
{% if j.eta_s %}, ETA ~{{(j.eta_s/60)|round}} min{% endif %}
{% if j.n_flagged is not none %}— {{j.n_flagged}} flagged, {{j.n_clips}} clips{% endif %}
{% if j.error %}<br><span class=failed>{{j.error}}</span>{% endif %}</div>
{% endfor %}
<script>setTimeout(()=>location.reload(),15000)</script>"""

DETAIL_HEAD = """<!doctype html><meta charset=utf-8><title>job {{j.id}}</title>
<style>body{font:15px/1.5 system-ui;max-width:1100px;margin:1.5em auto;padding:0 1em}
.seg{margin:4px 0}.w{cursor:pointer;padding:0 1px;border-radius:3px}
.w:hover{background:#eef}.flag{background:#ffd9d9}.edited{background:#dff5d2}
.sugg{display:none;background:#f8f8ff;border:1px solid #ccd;padding:4px 8px}
time{color:#888;font-size:12px}button{font-size:12px}</style>
<p><a href=/>&larr; jobs</a> — job <code>{{j.id}}</code> <b>{{j.state}}</b></p>
"""

DETAIL = DETAIL_HEAD + """
{% if t %}
{% if proposed_cuts %}
<h3>Smart-cut proposals ({{proposed_cuts|length}})</h3>
<form id=cutsform>{% for c in proposed_cuts %}
<label><input type=checkbox name=cut value="{{c.start}}-{{c.end}}">
 cut {{c.words|join(' ')}} @ {{'%.1f'|format(c.start)}}s ({{c.quality}})</label><br>{% endfor %}</form>
{% endif %}
<h3>Delete range (recut)</h3>
<div>start <input id=del_start size=6> s — end <input id=del_end size=6> s
<button onclick="delRange()">add cut</button></div>
<div id=op_cuts>{% for c in operator_cuts %}<div>✂ {{c[0]}}–{{c[1]}}s
 <button onclick="delOpCut('{{c[0]}}-{{c[1]}}')">undo</button></div>{% endfor %}</div>
<h3>Fix queue ({{flagged|length}} flagged)</h3>
{% for f in flagged %}
<div><b>{{f.word}}</b> @ {{f.t}}s — {{f.reasons|join(', ')}}
<button onclick="suggest({{f.seg}},{{f.idx}},this)">suggest</button><span class=sugg></span></div>
{% endfor %}
<form method=post action="/jobs/{{j.id}}/render" id=renderform>
<button type=button onclick="doRender()">Render clips (with checked cuts)</button></form>
<h3>Transcript</h3>
<audio id=player controls preload=none src="/jobs/{{j.id}}/audio"
 style="width:100%"></audio>
{% for s in t.segments %}<div class=seg><time>[{{'%.1f'|format(s.start)}}]</time>
{% for w in s.words %}<span class="w {% if w.flags %}flag{% endif %} {% if w.edited %}edited{% endif %}"
 onclick="seek({{w.start}})" ondblclick="edit({{s.id}},{{loop.index0}},this)"
 title="p={{w.prob}}{% if w.cyr %} | {{w.cyr}}{% endif %}{% if w.flags %} | {{w.flags|join(',')}}{% endif %} — click=seek, dblclick=edit">{{w.w}}</span> {% endfor %}</div>{% endfor %}
{% endif %}
<script>
async function edit(seg,idx,el){
 const nv=prompt('Edit word (Latin):',el.textContent); if(!nv||nv===el.textContent)return;
 const r=await fetch(`/jobs/{{j.id}}/edit`,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({seg,idx,word:nv})}); if(r.ok){el.textContent=nv;el.classList.add('edited');}}
async function suggest(seg,idx,el){
 const sp=el.parentElement.querySelector('.sugg'); sp.style.display='inline'; sp.textContent='…';
 const r=await fetch(`/jobs/{{j.id}}/suggest`,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({seg,idx})}); const d=await r.json();
 sp.innerHTML=''; (d.suggestions||[]).forEach(s=>{const b=document.createElement('button');
  b.textContent=s.text+' ('+s.source+')'; b.onclick=()=>accept(seg,idx,s.text,sp);
  sp.appendChild(b);}); if(!(d.suggestions||[]).length)sp.textContent='no suggestions';}
async function accept(seg,idx,text,sp){
 const r=await fetch(`/jobs/{{j.id}}/edit`,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({seg,idx,word:text})}); if(r.ok)location.reload();}
async function doRender(){
 const cuts=[...document.querySelectorAll('#cutsform input:checked')].map(c=>c.value);
 const r=await fetch(`/jobs/{{j.id}}/render`,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({cuts})}); const d=await r.json();
 alert(d.ok?'render queued':'error: '+(d.error||'')); if(d.ok)location.reload();}
async function delRange(){
 const s=parseFloat(del_start.value), e=parseFloat(del_end.value);
 if(isNaN(s)||isNaN(e)||e<=s){alert('bad range');return;}
 await fetch(`/jobs/{{j.id}}/delete_range`,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({start:s,end:e})}); location.reload();}
async function delOpCut(v){
 await fetch(`/jobs/{{j.id}}/delete_range`,{method:'POST',headers:{'Content-Type':'application/json'},
  body:JSON.stringify({remove:v})}); location.reload();}
function seek(t){const p=document.getElementById('player');p.currentTime=t;p.play();}
</script>"""


@app.get("/")
def index():
    videos = sorted(p.name for p in jobs.INPUT_DIR.glob("*.*")
                    if p.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv", ".webm", ".ts"))
    return render_template_string(INDEX, jobs=jobs.list_jobs(), videos=videos)


@app.post("/jobs")
def create():
    video = jobs.INPUT_DIR / request.form["video"]
    jid = jobs.create_job(
        video, engine=request.form.get("engine") or "sr-v3-ct2",
        hotwords_topic=request.form.get("hotwords_topic") or None,
        smart_cut=request.form.get("smart_cut", "off"),
        num_clips=int(request.form.get("num_clips", 5)))
    return redirect(url_for("detail", job_id=jid))


def _load(job_id: str):
    d = jobs.JOBS_DIR / job_id
    tp = d / "transcript.json"
    return d, (Transcript.load(tp) if tp.exists() else None)


@app.get("/jobs/<job_id>")
def detail(job_id):
    st = jobs.read_status(job_id) or {}
    st["id"] = job_id
    d, t = _load(job_id)
    flagged = []
    if t:
        for seg, w in t.iter_words():
            if w.flags:
                idx = seg.words.index(w)
                flagged.append({"seg": seg.id, "idx": idx, "word": w.w,
                                "t": round(w.start, 1), "reasons": w.flags})
    proposed_cuts = []
    cj = d / "clips.json"
    if cj.exists():
        proposed_cuts = json.loads(cj.read_text(encoding="utf-8")) \
            .get("proposed_cuts", [])
    operator_cuts = _op_cuts(d)
    return render_template_string(DETAIL, j=st, t=t, flagged=flagged,
                                  proposed_cuts=proposed_cuts,
                                  operator_cuts=operator_cuts)


@app.get("/jobs/<job_id>/transcript.json")
def transcript_json(job_id):
    d, t = _load(job_id)
    return jsonify(json.loads(t.json())) if t else ("not ready", 404)


@app.post("/jobs/<job_id>/edit")
def edit(job_id):
    body = request.get_json(force=True)
    with _edit_lock:
        d, t = _load(job_id)
        if t is None:
            return "no transcript", 404
        seg = next((s for s in t.segments if s.id == body["seg"]), None)
        if seg is None or not (0 <= int(body["idx"]) < len(seg.words)):
            return "bad seg/idx", 404
        w = seg.words[int(body["idx"])]
        w.w = body["word"].strip()
        w.edited = True              # contract: edits never touch w.cyr
        seg.text = " ".join(x.w for x in seg.words)
        t.save(d / "transcript.json")
    return jsonify(ok=True)


@app.post("/jobs/<job_id>/suggest")
def suggest(job_id):
    body = request.get_json(force=True)
    d, t = _load(job_id)
    if t is None:
        return "no transcript", 404
    seg = next((s for s in t.segments if s.id == body["seg"]), None)
    if seg is None or not (0 <= int(body["idx"]) < len(seg.words)):
        return "bad seg/idx", 404
    w = seg.words[int(body["idx"])]
    if not w.sugg:
        from .correct.tier0 import suggest as t0
        w.sugg = t0(w)
    if body.get("tier1"):
        from .correct import tier1
        existing = {s.text for s in w.sugg}
        w.sugg += [s for s in tier1.suggest(w, seg.text) if s.text not in existing]
    with _edit_lock:
        t.save(d / "transcript.json")
    return jsonify(suggestions=[s.dict() for s in w.sugg])


def _op_cuts(d: Path) -> list:
    p = d / "operator_cuts.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


@app.post("/jobs/<job_id>/delete_range")
def delete_range(job_id):
    """Operator-controlled deletion — explicit [start,end] source ranges.
    Stored alongside smart-cut proposals; render consumes the union."""
    body = request.get_json(force=True)
    d = jobs.JOBS_DIR / job_id
    cuts = _op_cuts(d)
    if "remove" in body:
        s, e = body["remove"].split("-")
        cuts = [c for c in cuts if not (abs(c[0] - float(s)) < 1e-3
                                        and abs(c[1] - float(e)) < 1e-3)]
    else:
        s, e = float(body["start"]), float(body["end"])
        if e <= s:
            return jsonify(error="end <= start"), 400
        cuts.append([s, e])
    (d / "operator_cuts.json").write_text(
        json.dumps(sorted(cuts), ensure_ascii=False), encoding="utf-8")
    return jsonify(ok=True, cuts=cuts)


@app.get("/jobs/<job_id>/audio")
def audio(job_id):
    wav = jobs.JOBS_DIR / job_id / "audio_16k.wav"
    if not wav.exists():
        return "no audio", 404
    return send_file(wav, mimetype="audio/wav", conditional=True)


@app.post("/jobs/<job_id>/render")
def render(job_id):
    st = jobs.read_status(job_id) or {}
    if st.get("state") not in ("transcribed", "done"):
        return jsonify(error="job not transcribed yet"), 409
    body = request.get_json(force=True, silent=True) or {}
    # union: operator-accepted proposals + operator delete-ranges
    accepted = []
    for item in body.get("cuts", []):
        try:
            s, e = item.split("-")
            accepted.append((float(s), float(e)))
        except Exception:
            continue
    d0 = jobs.JOBS_DIR / job_id
    accepted += [tuple(c) for c in _op_cuts(d0)]

    def _bg():
        try:
            from .render import render_clip
            from .types import Transcript
            d = jobs.JOBS_DIR / job_id
            t = Transcript.load(d / "transcript.json")
            clips = json.loads((d / "clips.json").read_text(encoding="utf-8"))["clips"]
            jobs._write_status(job_id, state="rendering", stage="render")
            metas = [render_clip(Path(st["video"]), t, c, d, i + 1,
                                 cuts=[x for x in accepted if c["start"] <= x[0] < c["end"]])
                     for i, c in enumerate(clips)]
            jobs._write_status(job_id, state="done", rendered=len(metas))
        except Exception as e:
            logger.exception("render failed")
            jobs._write_status(job_id, state="render_failed", error=str(e))
    threading.Thread(target=_bg, daemon=True).start()
    return jsonify(ok=True)


def main():
    app.run(host="127.0.0.1", port=7860, threaded=True)


if __name__ == "__main__":
    main()
