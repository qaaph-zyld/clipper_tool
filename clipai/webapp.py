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

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

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
— stage: {{j.stage or '—'}}{% if j.eta_s %}, ETA ~{{(j.eta_s/60)|round}} min{% endif %}
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
<h3>Fix queue ({{flagged|length}} flagged)</h3>
{% for f in flagged %}
<div><b>{{f.word}}</b> @ {{f.t}}s — {{f.reasons|join(', ')}}
<button onclick="suggest({{f.seg}},{{f.idx}},this)">suggest</button><span class=sugg></span></div>
{% endfor %}
<h3>Transcript</h3>
{% for s in t.segments %}<div class=seg><time>[{{'%.1f'|format(s.start)}}]</time>
{% for w in s.words %}<span class="w {% if w.flags %}flag{% endif %} {% if w.edited %}edited{% endif %}"
 onclick="edit({{s.id}},{{loop.index0}},this)"
 title="p={{w.prob}}{% if w.cyr %} | {{w.cyr}}{% endif %}{% if w.flags %} | {{w.flags|join(',')}}{% endif %}">{{w.w}}</span> {% endfor %}</div>{% endfor %}
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
    return render_template_string(DETAIL, j=st, t=t, flagged=flagged)


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
        seg = next(s for s in t.segments if s.id == body["seg"])
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
    seg = next(s for s in t.segments if s.id == body["seg"])
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


@app.post("/jobs/<job_id>/render")
def render(job_id):
    st = jobs.read_status(job_id) or {}
    if st.get("state") != "transcribed":
        return jsonify(error="job not transcribed yet"), 409
    _write = jobs._write_status(job_id, render_queued=True)
    def _bg():
        try:
            from .render import render_clip
            from .types import Transcript
            d = jobs.JOBS_DIR / job_id
            t = Transcript.load(d / "transcript.json")
            clips = json.loads((d / "clips.json").read_text(encoding="utf-8"))["clips"]
            cuts = [(c["start"], c["end"]) for c in
                    json.loads((d / "clips.json").read_text(encoding="utf-8"))
                    .get("proposed_cuts", [])]
            jobs._write_status(job_id, state="rendering", stage="render")
            metas = [render_clip(Path(st["video"]), t, c, d, i + 1,
                                 cuts=[x for x in cuts if c["start"] <= x[0] < c["end"]])
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
