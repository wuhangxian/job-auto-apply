#!/usr/bin/env python3
"""求职 Agent Web UI v2 — 完全重写。"""

from __future__ import annotations
import json, sys, threading
from pathlib import Path

from flask import Flask, request, jsonify, Response

_root = str(Path(__file__).resolve().parents[1])
if _root not in sys.path:
    sys.path.insert(0, _root)

from agent.config import load_config, load_profile_text
from agent.database import Database
from agent.ai import AIClient, score_job, generate_progress_summary, generate_application_answers
from agent.collectors import collect_tencent_docs, collect_boss, collect_liepin, collect_web
from agent.applicator import Applicator
from agent.reporter import generate_report, save_report

app = Flask(__name__)
CONFIG_PATH = str(Path(__file__).resolve().parent / "config.yaml")
_run_state = {"running": False, "log": "", "done": False, "error": None, "summary": "", "stats": {}}

def get_config(): return load_config(CONFIG_PATH)
def get_db(): return Database(get_config().output.database)

HTML = '''<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>求职 Agent</title>
<style>
:root{--bg:#0d1117;--card:#161b22;--bd:#30363d;--tx:#c9d1d9;--mu:#8b949e;--teal:#2ee6a8;--am:#f0b429;--rd:#f85149;--bl:#58a6ff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--tx);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;font-size:14px;line-height:1.6}
a{color:var(--teal);text-decoration:none}
button{cursor:pointer;font-family:inherit}
.hd{background:#161b22;border-bottom:1px solid var(--bd);padding:10px 24px;display:flex;align-items:center;gap:12px}
.hd h1{font-size:18px}
.hd .st{margin-left:auto;font-size:13px;color:var(--mu)}
.hd .st b{color:var(--tx)}
.tabs{display:flex;background:var(--bg);border-bottom:1px solid var(--bd);padding:0 24px}
.tabs button{background:none;border:none;color:var(--mu);padding:10px 18px;cursor:pointer;font-size:14px;border-bottom:2px solid transparent}
.tabs button.on{color:var(--teal);border-bottom-color:var(--teal)}
.wrap{padding:20px;max-width:1100px;margin:0 auto}
.card{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:14px;margin-bottom:10px}
.card.hl{border-left:3px solid var(--teal)}
.btn{background:var(--teal);color:#0d1117;border:none;border-radius:4px;padding:7px 16px;font-size:14px;font-weight:700}
.btn:hover{opacity:.85}
.btn.sec{background:var(--bd);color:var(--tx)}
.btn.dng{background:var(--rd);color:#fff}
.btn.sm{padding:3px 10px;font-size:12px}
.btn.bl{background:var(--bl);color:#fff}
.badge{display:inline-block;padding:2px 7px;border-radius:10px;font-size:11px;font-weight:600;color:#fff}
.badge.new{background:#1f6feb}.badge.applied{background:#238636}.badge.pending{background:var(--am);color:#000}.badge.rejected{background:var(--rd)}
.sc{font-size:22px;font-weight:800;width:44px;text-align:center;flex-shrink:0}
.sc.h{color:var(--teal)}.sc.m{color:var(--am)}.sc.l{color:var(--rd)}
.row{display:flex;gap:12px;align-items:flex-start}
.row .main{flex:1;min-width:0}
.jt{font-weight:700;font-size:15px}
.jm{color:var(--mu);font-size:13px;margin-top:2px}
.jr{font-size:13px;margin-top:4px}
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:6px;border-bottom:1px solid var(--bd);color:var(--mu);font-size:12px}
td{padding:6px;border-bottom:1px solid var(--bd);font-size:13px}
pre{background:#0d1117;border:1px solid var(--bd);border-radius:4px;padding:10px;overflow-x:auto;font-size:13px;white-space:pre-wrap;max-height:150px}
.log{background:#0d1117;border:1px solid var(--bd);border-radius:4px;padding:12px;height:400px;overflow-y:auto;font-family:monospace;font-size:13px;white-space:pre-wrap;line-height:1.7}
.modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.7);display:flex;align-items:center;justify-content:center;z-index:100}
.modal-c{background:var(--card);border:1px solid var(--bd);border-radius:8px;padding:20px;max-width:700px;width:92%;max-height:85vh;overflow-y:auto}
.fg{margin-bottom:10px}
.fg label{display:block;font-size:12px;color:var(--mu);margin-bottom:3px}
input,textarea,select{width:100%;background:#0d1117;border:1px solid var(--bd);border-radius:4px;color:var(--tx);padding:7px 10px;font-size:14px}
input:focus,textarea:focus{outline:none;border-color:var(--teal)}
.pgrid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:16px}
.pgrid .ps{text-align:center}.pgrid .ps .pn{font-size:26px;font-weight:800}.pgrid .ps .pl{font-size:11px;color:var(--mu)}
.detail-box{margin:8px 0;padding:8px 12px;border-radius:4px;border-left:3px solid}
.detail-box.good{border-color:var(--teal);background:rgba(46,230,168,.06);color:var(--teal)}
.detail-box.warn{border-color:var(--am);background:rgba(240,180,41,.06);color:var(--am)}
</style></head><body>
<div class="hd"><h1>\u25a6 \u6c42\u804c Agent</h1><div class="st" id="nav-st">\u52a0\u8f7d\u4e2d...</div></div>
<div class="tabs">
  <button onclick="tab('dash')" id="t-dash" class="on">\u8fdb\u5ea6\u770b\u677f</button>
  <button onclick="tab('jobs')" id="t-jobs">\u5c97\u4f4d\u5217\u8868</button>
  <button onclick="tab('review')" id="t-review">\u5f85\u5ba1\u6838</button>
  <button onclick="tab('cfg')" id="t-cfg">\u914d\u7f6e</button>
</div>
<div class="wrap" id="main">Loading...</div>
<div id="modal-here"></div>
<script>
function tab(n){document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('on'));document.getElementById('t-'+n).classList.add('on');document.getElementById('main').innerHTML='Loading...';fetch('/api/'+n).then(r=>r.text()).then(h=>document.getElementById('main').innerHTML=h)}
var _t=null;
function runAgent(){document.getElementById('main').innerHTML='<div class="card"><h2>Agent \u8fd0\u884c\u4e2d</h2><div class="log" id="log">\u542f\u52a8\u4e2d...</div><div id="result"></div></div>';fetch('/api/run',{method:'POST'}).then(r=>r.json()).then(d=>{if(d.error){document.getElementById('log').textContent=d.error;return}_t=setInterval(poll,1000)})}
function poll(){fetch('/api/run-status').then(r=>r.json()).then(d=>{var log=document.getElementById('log');if(!log)return;if(d.log)log.textContent=d.log;if(d.done){clearInterval(_t);_t=null;if(d.error){log.textContent+='\\n\\n\u2717 '+d.error;log.style.color='var(--rd)'}else{log.style.color='var(--teal)';log.textContent+='\\n\\n=== \u5b8c\u6210 ==='}var r=document.getElementById('result');if(d.summary)r.innerHTML='<div class="card hl"><h3>AI \u603b\u7ed3</h3><pre>'+d.summary+'</pre></div>';r.innerHTML+='<div class="card"><button class="btn" onclick="goDash()">\u67e5\u770b\u7ed3\u679c</button></div>';updateStats()}})}
function updateStats(){fetch('/api/stats').then(r=>r.json()).then(s=>document.getElementById('nav-st').innerHTML='\u603b\u8ba1 <b>'+s.total+'</b> | \u5df2\u6295 <b>'+s.applied+'</b> | \u5f85\u5ba1 <b>'+s.pending_review+'</b>')}
function showJob(id){fetch('/api/job/'+id).then(r=>r.json()).then(d=>{var h='<div class="modal" onclick="this.remove()"><div class="modal-c" onclick="event.stopPropagation()">';h+='<h2>'+d.company+'</h2>';h+='<p class="jm">'+d.title+'</p>';h+='<p class="jm">\u5206\u6570: <b style="color:var(--teal)">'+d.score+'</b> | \u5730\u70b9: '+d.location+' | \u85aa\u8d44: '+d.salary+' | \u6765\u6e90: '+d.source+'</p>';h+='<p style="margin:8px 0;color:var(--teal)">'+d.score_reason+'</p>';if(d.match_points&&d.match_points.length){h+='<div class="detail-box good"><b>\u2713 \u5339\u914d\u70b9</b>';d.match_points.forEach(function(p){h+='<div>'+p+'</div>'});h+='</div>'}if(d.concerns&&d.concerns.length){h+='<div class="detail-box warn"><b>\u26a0 \u987e\u8651</b>';d.concerns.forEach(function(c){h+='<div>'+c+'</div>'});h+='</div>'}if(d.jd){h+='<h3 style="margin-top:10px">\u5c97\u4f4d\u63cf\u8ff0</h3><pre>'+d.jd+'</pre>'}h+='<a href="'+d.url+'" target="_blank" style="display:inline-block;margin:8px 0">\u6253\u5f00\u5c97\u4f4d\u9875\u9762 \u2192</a>';if(d.status!=='applied')h+='<br><br><button class="btn" onclick="previewApply('+id+')">AI \u586b\u8868\u51c6\u5907\u6295\u9012</button>';h+='</div></div>';document.getElementById('modal-here').innerHTML=h})}
function previewApply(id){
  document.getElementById('modal-here').innerHTML='<div class="modal"><div class="modal-c"><h2>AI 浏览器自动填表</h2><p>正在打开浏览器并填写表单，请稍候...</p><div style="text-align:center;padding:20px"><div style="display:inline-block;width:40px;height:40px;border:4px solid var(--bd);border-top-color:var(--teal);border-radius:50%;animation:spin 1s linear infinite"></div></div><style>@keyframes spin{to{transform:rotate(360deg)}}</style></div></div>';
  fetch('/api/preview-apply/'+id).then(r=>r.json()).then(d=>{
    if(d.error){alert(d.error);return}
    var h='<div class="modal" onclick="this.remove()"><div class="modal-c" onclick="event.stopPropagation()" style="max-width:800px">';
    h+='<h2>'+d.company+'</h2>';
    h+='<p class="jm">'+d.title+'</p>';
    if(d.fill_result && d.fill_result.steps){
      var fr=d.fill_result;
      h+='<div style="padding:8px;border:1px solid var(--bd);border-radius:4px;margin:10px 0;background:#0d1117">';
      h+='<b>页面:</b> '+fr.page_title+'<br>';
      h+='<b>页面URL:</b> <a href="'+fr.page_url+'" target="_blank" style="font-size:11px;word-break:break-all">'+fr.page_url+'</a><br>';
      h+='<b>检测到字段:</b> '+fr.fields_detected+'<br>';
      h+='<b>已填写:</b> '+fr.fields_filled+'<br>';
      if(fr.error)h+='<div style="color:var(--rd)">错误: '+fr.error+'</div>';
      h+='</div>';
      h+='<h3>自动填表过程</h3>';
      fr.steps.forEach(function(s){
        var color=s.status==='ok'?'var(--teal)':(s.status==='skip'?'var(--mu)':'var(--rd)');
        h+='<div class="card" style="margin:6px 0;padding:8px">';
        h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">';
        h+='<b style="font-size:13px">第'+s.step+'步: '+s.action+'</b>';
        h+='<span style="font-size:11px;color:'+color+'">'+s.status+'</span></div>';
        if(s.detail)h+='<div style="font-size:12px;color:var(--mu);margin-bottom:4px">'+s.detail+'</div>';
        if(s.url)h+='<div style="font-size:11px;color:var(--bl);word-break:break-all;margin-bottom:4px"><a href="'+s.url+'" target="_blank">'+s.url+'</a></div>';
        if(s.screenshot)h+='<img src="data:image/png;base64,'+s.screenshot+'" style="width:100%;border:1px solid var(--bd);border-radius:4px;margin-top:4px">';
        h+='</div>';
      });
    } else if(d.answers&&d.answers.length){
} else if(d.answers&&d.answers.length){
      h+='<h3>AI 填写的内容</h3>';
      h+='<table><thead><tr><th>字段</th><th>AI 填写值</th></tr></thead><tbody>';
      d.answers.forEach(function(a){h+='<tr><td style="width:30%;color:var(--mu);vertical-align:top">'+a.field_name+'</td><td><pre style="margin:0;max-height:100px">'+a.value+'</pre></td></tr>';})
      h+='</tbody></table>';
      h+='<p style="color:var(--mu);font-size:12px">此页面未检测到可自动填写的表单，以上为 AI 生成的填写内容，请手动复制到投递页面</p>';
    } else {
      h+='<p style="color:var(--mu)">未生成填写内容</p>';
    }
    h+='<hr style="border-color:var(--bd);margin:12px 0">';
    h+='<a href="'+d.url+'" target="_blank"><button class="btn bl">打开原始投递页面</button></a> ';
    h+='<button class="btn sec" onclick="approveJob('+id+')">已投递，标记完成</button> ';
    h+='<button class="btn dng" onclick="rejectJob('+id+')">不投了</button>';
    h+='</div></div>';
    document.getElementById('modal-here').innerHTML=h;
  });
}
function approveJob(id){fetch('/api/approve/'+id,{method:'POST'}).then(()=>{document.getElementById('modal-here').innerHTML='';tab('dash')})}
function rejectJob(id){fetch('/api/reject/'+id,{method:'POST'}).then(()=>{document.getElementById('modal-here').innerHTML='';tab('dash')})}
function saveCfg(){var d={};new FormData(document.getElementById('cfg-form')).forEach(function(v,k){d[k]=v});fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}).then(r=>r.json()).then(r=>alert(r.ok?'\u914d\u7f6e\u5df2\u4fdd\u5b58':r.error))}
tab('dash');updateStats();setInterval(updateStats,10000)
</script></body></html>'''

@app.route("/")
def index(): return HTML

@app.route("/api/stats")
def api_stats(): return jsonify(get_db().stats())

@app.route("/api/dash")
def api_dash():
    db=get_db();s=db.stats();top=db.list_jobs(min_score=0,limit=20)
    h='<div class="pgrid">'
    for k,label in [("total","\u91c7\u96c6"),("applied","\u5df2\u6295"),("pending_review","\u5f85\u5ba1"),("rejected","\u88ab\u62d2"),("high_score_unapplied","\u9ad8\u5206\u672a\u6295")]:
        c="var(--teal)" if k=="high_score_unapplied" and s.get(k,0)>0 else "var(--tx)"
        h+='<div class="ps"><div class="pn" style="color:'+c+'">'+str(s.get(k,0))+'</div><div class="pl">'+label+'</div></div>'
    h+='</div><div class="card"><button class="btn" onclick="runAgent()">\u25b6 \u8fd0\u884c Agent\uff08\u91c7\u96c6\u2192\u8bc4\u5206\u2192\u6295\u9012\uff09</button></div>'
    if top:
        h+='<h2 style="margin:14px 0 6px;font-size:15px">Top \u5c97\u4f4d (\u5171 '+str(len(top))+' \u4e2a)</h2>'
        for j in top[:15]:
            sc="h" if j.score>=70 else("m" if j.score>=50 else "l")
            b='<span class="badge '+j.status+'">'+j.status+'</span>' if j.status!="new" else ""
            h+='<div class="card hl" onclick="showJob('+str(j.id)+')"><div class="row"><div class="sc '+sc+'">'+str(j.score)+'</div><div class="main"><div class="jt">'+j.company+' - '+j.title+' '+b+'</div><div class="jm">'+j.location+' | '+j.salary+' | '+j.source+'</div><div class="jr">'+j.score_reason+'</div></div></div></div>'
    return h

@app.route("/api/jobs")
def api_jobs():
    db=get_db();jobs=db.list_jobs(min_score=0,limit=500)
    total=len(jobs)
    scored=len([j for j in jobs if j.score>0])
    h='<div class="card" style="display:flex;gap:20px;align-items:center"><div style="font-size:20px;font-weight:700">\u603b\u8ba1 <span style="color:var(--teal)">'+str(total)+'</span> \u4e2a\u5c97\u4f4d</div><div style="color:var(--mu);font-size:13px">\u5df2\u8bc4\u5206 '+str(scored)+' \u4e2a</div></div>'
    h+='<table><thead><tr><th>\u5206\u6570</th><th>\u516c\u53f8</th><th>\u5c97\u4f4d</th><th>\u5730\u70b9</th><th>\u85aa\u8d44</th><th>\u6765\u6e90</th><th>\u72b6\u6001</th><th>\u64cd\u4f5c</th></tr></thead><tbody>'
    for j in jobs:
        sc="h" if j.score>=70 else("m" if j.score>=50 else "l")
        b='<span class="badge '+j.status+'">'+j.status+'</span>' if j.status!="new" else '<span class="badge new">new</span>'
        btn='<button class="btn sm" onclick="event.stopPropagation();previewApply('+str(j.id)+')">\u6295\u9012</button>' if j.status=="new" else ''
        h+='<tr style="cursor:pointer" onclick="showJob('+str(j.id)+')"><td class="sc '+sc+'">'+str(j.score)+'</td><td>'+j.company+'</td><td>'+j.title+'</td><td>'+j.location+'</td><td>'+j.salary+'</td><td>'+j.source+'</td><td>'+b+'</td><td>'+btn+'</td></tr>'
    h+='</tbody></table>'
    if total>=500:h+='<p style="color:var(--mu);font-size:12px;margin-top:8px">Showing first 500 only</p>'
    return h

@app.route("/api/review")
def api_review():
    db=get_db();pending=db.list_jobs(status="pending_review",limit=50)
    if not pending: return '<div class="card"><p style="color:var(--mu)">\u6ca1\u6709\u5f85\u5ba1\u6838\u7684\u6295\u9012\u3002</p></div>'
    h=''
    for j in pending:
        h+='<div class="card hl"><div class="row"><div class="sc h">'+str(j.score)+'</div><div class="main"><div class="jt">'+j.company+' - '+j.title+'</div><div class="jm">'+j.location+' | '+j.salary+' | '+j.source+'</div><div class="jr">'+j.review_notes+'</div><a href="'+j.url+'" target="_blank">\u6253\u5f00\u6295\u9012\u9875\u9762 \u2192</a></div><div style="display:flex;flex-direction:column;gap:4px"><button class="btn sm" onclick="previewApply('+str(j.id)+')">\u67e5\u770bAI\u586b\u8868</button><button class="btn sm" onclick="approveJob('+str(j.id)+')">\u786e\u8ba4</button><button class="btn dng sm" onclick="rejectJob('+str(j.id)+')">\u62d2\u7edd</button></div></div></div>'
    return h

@app.route("/api/cfg")
def api_cfg():
    import html as html_mod
    try: c=get_config()
    except: c=None
    try: pt=load_profile_text(c) if c else ""
    except: pt=""
    src=c.sources if c else {}
    td=src.get("tencent_docs")
    bs=src.get("boss")
    lp=src.get("liepin")
    vals = {
        "ab": html_mod.escape(c.ai.base_url if c else ""),
        "ak": html_mod.escape(c.ai.api_key if c else ""),
        "am": html_mod.escape(c.ai.model if c else ""),
        "tt": html_mod.escape(td.token if td else ""),
        "tf": html_mod.escape(",".join(td.file_ids) if td and td.file_ids else "DRHVEc05MbE5CYUZa"),
        "bt": html_mod.escape(bs.token if bs else ""),
        "bk": html_mod.escape(",".join(bs.keywords) if bs and bs.keywords else "AI Infra,C++"),
        "lc": html_mod.escape(lp.cookie if lp else ""),
        "aa": "checked" if c and c.auto_apply.enabled else "",
        "pl": "loaded " + str(len(pt)) + " chars" if pt else "not loaded",
    }
    return """<div class="card"><h2>Config</h2><form id="cfg-form">
    <div class="fg"><label>AI Base URL</label><input name="ai_base_url" value="{ab}"></div>
    <div class="fg"><label>API Key</label><input name="ai_api_key" type="password" value="{ak}" placeholder="Your API Key"></div>
    <div class="fg"><label>Model</label><input name="ai_model" value="{am}" placeholder="GLM-5.2-TokenHub"></div>
    <hr style="border-color:var(--bd);margin:12px 0">
    <div class="fg"><label>Tencent Token</label><input name="tencent_token" type="password" value="{tt}" placeholder="Tencent Token"></div>
    <div class="fg"><label>Tencent File IDs</label><input name="tencent_file_ids" value="{tf}"></div>
    <hr style="border-color:var(--bd);margin:12px 0">
    <div class="fg"><label>Boss Token (wt2)</label><input name="boss_token" type="password" value="{bt}" placeholder="Boss wt2"></div>
    <div class="fg"><label>Boss Keywords</label><input name="boss_keywords" value="{bk}"></div>
    <div class="fg"><label>Liepin Cookie</label><textarea name="liepin_cookie" rows="2" placeholder="Liepin cookie">{lc}</textarea></div>
    <hr style="border-color:var(--bd);margin:12px 0">
    <div class="fg"><label><input type="checkbox" name="auto_apply" value="true" {aa}> Enable auto apply</label></div>
    <button type="button" class="btn" onclick="saveCfg()">Save</button></form>
    <hr style="border-color:var(--bd);margin:12px 0">
    <p style="color:var(--mu);font-size:12px">Profile: {pl}</p></div>""".format(**vals)


@app.route("/api/config",methods=["POST"])
def api_save_cfg():
    d=request.get_json(force=True);import yaml
    cfg={"ai":{"base_url":d.get("ai_base_url",""),"api_key":d.get("ai_api_key",""),"model":d.get("ai_model","")},"profile":{"cv_md":"../cv.md","resume_pdf":"/data/home/dorianwu/whx-study/\u5434\u822a\u5148_\u7b80\u53860720\uff08\u4fee\uff09.pdf","profile_yml":"../config/profile.yml","application_profile":"../config/private-application-profile.md","voice_dna":"../voice-dna.md"},"sources":{"tencent_docs":{"enabled":bool(d.get("tencent_token")),"token":d.get("tencent_token",""),"file_ids":[s.strip() for s in d.get("tencent_file_ids","").split(",") if s.strip()],"tables":[]},"boss":{"enabled":bool(d.get("boss_token")),"token":d.get("boss_token",""),"keywords":[s.strip() for s in d.get("boss_keywords","").split(",") if s.strip()],"cities":["\u5408\u80a5","\u5357\u4eac","\u676d\u5dde","\u4e0a\u6d77","\u6df1\u5733","\u5317\u4eac"],"max_results":50},"liepin":{"enabled":bool(d.get("liepin_cookie")),"cookie":d.get("liepin_cookie",""),"keywords":["AI Infra","LLM Serving"],"cities":["\u5408\u80a5","\u5357\u4eac","\u676d\u5dde","\u4e0a\u6d77"],"max_results":30}},"scoring":{"min_score":60,"weights":{"match":35,"growth":15,"location":20,"stability":15,"salary":15},"city_priority":["\u5408\u80a5","\u5357\u4eac","\u676d\u5dde","\u4e0a\u6d77","\u6df1\u5733","\u5317\u4eac","\u5e7f\u5dde"],"preferred_industries":["\u5236\u9020\u4e1a","\u667a\u80fd\u6c7d\u8f66","\u673a\u5668\u4eba","\u534a\u5bfc\u4f53","\u5de5\u4e1a AI","\u56fd\u592e\u4f01\u79d1\u6280","\u91d1\u878d\u79d1\u6280"],"exclude_companies":[]},"auto_apply":{"enabled":d.get("auto_apply")=="true","require_review":True,"batch_size":5,"interval_seconds":30},"output":{"reports_dir":"../reports/agent","database":"../data/agent.db"}}
    with open(CONFIG_PATH,"w",encoding="utf-8") as f:yaml.dump(cfg,f,allow_unicode=True,default_flow_style=False)
    return jsonify({"ok":True})

@app.route("/api/run",methods=["POST"])
def api_run():
    if _run_state.get("running"):return jsonify({"error":"Agent running"})
    _run_state.update({"running":True,"log":"","done":False,"error":None,"summary":"","stats":{}})
    threading.Thread(target=_run_agent,daemon=True).start()
    return jsonify({"ok":True,"message":"started"})

def _run_agent():
    import io;buf=io.StringIO()
    try:
        c=get_config()
        if not c.ai.api_key:_run_state["log"]="Please set AI API Key";_run_state["error"]="Please set AI API Key";return
        db=get_db();pt=load_profile_text(c);ai=AIClient(c.ai.base_url,c.ai.api_key,c.ai.model);all_jobs=[];srcs=c.sources
        if srcs.get("tencent_docs") and srcs["tencent_docs"].enabled and srcs["tencent_docs"].token:
            buf.write("Tencent collecting...\n");_run_state["log"]=buf.getvalue()
            try:
                js=collect_tencent_docs(srcs["tencent_docs"].token,srcs["tencent_docs"].file_ids,srcs["tencent_docs"].tables or None)
                buf.write("  Tencent: "+str(len(js))+"\n");_run_state["log"]=buf.getvalue();all_jobs.extend(js)
            except Exception as e:buf.write("  Tencent fail: "+str(e)+"\n");_run_state["log"]=buf.getvalue()
        if srcs.get("boss") and srcs["boss"].enabled and srcs["boss"].token:
            buf.write("Boss searching...\n");_run_state["log"]=buf.getvalue()
            try:
                js=collect_boss(srcs["boss"].token,srcs["boss"].keywords,srcs["boss"].cities,srcs["boss"].max_results)
                buf.write("  Boss: "+str(len(js))+"\n");_run_state["log"]=buf.getvalue();all_jobs.extend(js)
            except Exception as e:buf.write("  Boss fail: "+str(e)+"\n");_run_state["log"]=buf.getvalue()
        if srcs.get("liepin") and srcs["liepin"].enabled and srcs["liepin"].cookie:
            buf.write("Liepin searching...\n");_run_state["log"]=buf.getvalue()
            try:
                js=collect_liepin(srcs["liepin"].cookie,srcs["liepin"].keywords,srcs["liepin"].cities,srcs["liepin"].max_results)
                buf.write("  Liepin: "+str(len(js))+"\n");_run_state["log"]=buf.getvalue();all_jobs.extend(js)
            except Exception as e:buf.write("  Liepin fail: "+str(e)+"\n");_run_state["log"]=buf.getvalue()
        buf.write("Total: "+str(len(all_jobs))+"\n");_run_state["log"]=buf.getvalue()
        for j in all_jobs:db.upsert_job(source=j.source,company=j.company,title=j.title,url=j.url,location=j.location,salary=j.salary,jd=j.jd)
        unscored=[j for j in db.list_jobs(min_score=0,limit=1000) if j.score==0]
        buf.write("To score: "+str(len(unscored))+"\n");_run_state["log"]=buf.getvalue()
        sc_cfg={"weights":c.scoring.weights,"city_priority":c.scoring.city_priority,"preferred_industries":c.scoring.preferred_industries,"exclude_companies":c.scoring.exclude_companies}
        for i,j in enumerate(unscored[:500]):
            try:
                r=score_job(ai,pt,{"company":j.company,"title":j.title,"location":j.location,"salary":j.salary,"jd":j.jd,"source":j.source},sc_cfg)
                dim_data=[]
                for d in r.dimensions:
                    dim_data.append({"name":d.name,"score":d.score,"weight":d.weight,"weighted":d.max_score,"reason":d.reason})
                detail=json.dumps({"match_points":r.match_points,"concerns":r.concerns,"dimensions":dim_data},ensure_ascii=False)
                db.set_score(j.id,r.score,r.reason,detail)
                buf.write("  ["+str(i+1)+"/"+str(len(unscored[:500]))+"] "+j.company+": "+str(r.score)+"\n");_run_state["log"]=buf.getvalue()
            except Exception as e:
                db.set_score(j.id,1,"score failed");buf.write("  ["+str(i+1)+"] "+j.company+" fail\n");_run_state["log"]=buf.getvalue()
        stats=db.stats();scored=db.list_jobs(min_score=0,limit=500);summary=""
        try:
            recent=[{"company":j.company,"title":j.title,"score":j.score,"status":j.status} for j in scored[:20]]
            summary=generate_progress_summary(ai,stats,recent)
        except:pass
        report=generate_report(scored,stats,summary);save_report(report,c.output.reports_dir)
        _run_state["log"]=buf.getvalue();_run_state["summary"]=summary;_run_state["stats"]=stats
    except Exception as e:_run_state["log"]=buf.getvalue();_run_state["error"]=str(e)
    finally:_run_state["done"]=True;_run_state["running"]=False

@app.route("/api/run-status")
def api_run_status():
    return jsonify({"running":_run_state["running"],"log":_run_state["log"],"done":_run_state["done"],"error":_run_state["error"],"summary":_run_state["summary"],"stats":_run_state["stats"]})

@app.route("/api/job/<int:job_id>")
def api_job(job_id):
    db=get_db()
    for j in db.list_jobs(limit=500):
        if j.id==job_id:
            mp=[];cn=[]
            mp=[];cn=[];dims=[]
            try:
                detail=json.loads(j.score_detail) if j.score_detail else {}
                if isinstance(detail,dict):
                    mp=detail.get("match_points",[])
                    cn=detail.get("concerns",[])
                    dims=detail.get("dimensions",[])
            except:pass
            return jsonify({"company":j.company,"title":j.title,"score":j.score,"location":j.location,"salary":j.salary,"jd":j.jd,"url":j.url,"score_reason":j.score_reason,"status":j.status,"source":j.source,"match_points":mp,"concerns":cn,"dimensions":dims})
    return jsonify({"error":"not found"}),404

@app.route("/api/preview-apply/<int:job_id>")
def api_preview(job_id):
    c=get_config();db=get_db()
    for j in db.list_jobs(limit=500):
        if j.id==job_id:
            if not c.ai.api_key:return jsonify({"error":"Please set AI API Key"})
            ai=AIClient(c.ai.base_url,c.ai.api_key,c.ai.model);pt=load_profile_text(c)
            vd=""
            if c.profile.voice_dna and Path(c.profile.voice_dna).exists():vd=Path(c.profile.voice_dna).read_text(encoding="utf-8")
            ap=Applicator(ai,pt,vd,require_review=True);ff=ap._detect_form_fields(j.url)
            answers=[]
            try:answers=generate_application_answers(ai,pt,vd,{"company":j.company,"title":j.title,"jd":j.jd,"url":j.url,"source":j.source},ff)
            except:answers=[]
            db.set_status(j.id,"pending_review");db.set_review(j.id,"pending","AI auto apply")
            profile_data={"name":"吴航先","phone":"16750118448","email":"1391938827@qq.com","school":"中国科学技术大学","major":"电子信息（人工智能）"}
            from agent.smart_apply import smart_apply
            sr=smart_apply(j.company,j.title,j.url,ai.chat,answers,profile_data,headless=True)
            return jsonify({
                "company":j.company,
                "title":j.title,
                "url":j.url,
                "answers":answers,
                "fill_result":{
                    "steps":[{"step":s.step,"action":s.action,"detail":s.detail,"screenshot":s.screenshot,"url":s.url,"status":s.status} for s in sr.steps],
                    "final_screenshot":sr.final_screenshot,
                    "page_title":sr.page_title,
                    "page_url":sr.page_url,
                    "form_found":sr.form_found,
                    "fields_detected":sr.fields_detected,
                    "fields_filled":sr.fields_filled,
                    "error":sr.error,
                }
            })
    return jsonify({"error":"Job not found"})

@app.route("/api/approve/<int:job_id>",methods=["POST"])
def api_approve(job_id):
    db=get_db();db.mark_applied(job_id);db.set_review(job_id,"approved","user approved");return jsonify({"ok":True})

@app.route("/api/reject/<int:job_id>",methods=["POST"])
def api_reject(job_id):
    db=get_db();db.set_status(job_id,"rejected");db.set_review(job_id,"rejected","user rejected");return jsonify({"ok":True})

if __name__=="__main__":app.run(host="0.0.0.0",port=5000,debug=False)
