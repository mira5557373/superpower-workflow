from __future__ import annotations

UNIFIED_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Superpower Workflow — Unified Dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Courier New',monospace;background:#1a1a2e;color:#e0e0e0;min-height:100vh}
a{color:#4fc3f7;text-decoration:none}a:hover{text-decoration:underline}
nav{background:#16213e;padding:12px 24px;display:flex;gap:24px;align-items:center;border-bottom:1px solid #0f3460}
nav .brand{font-size:16px;font-weight:bold;color:#e94560}
nav a{font-size:14px;padding:4px 8px;border-radius:4px}
nav a.active{background:#0f3460}
.container{max-width:1200px;margin:0 auto;padding:24px}
.card{background:#16213e;border:1px solid #0f3460;border-radius:8px;padding:16px;margin-bottom:16px}
.card h3{color:#4fc3f7;margin-bottom:8px;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
.stat{display:inline-block;margin-right:24px;margin-bottom:8px}
.stat .label{font-size:11px;color:#888;text-transform:uppercase}
.stat .value{font-size:20px;font-weight:bold;color:#e94560}
.status-ok{color:#4caf50}.status-fail{color:#f44336}.status-run{color:#ff9800}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #0f3460}
th{color:#888;font-size:11px;text-transform:uppercase}
.search-bar{width:100%;padding:8px 12px;background:#0f3460;border:1px solid #1a1a2e;color:#e0e0e0;border-radius:4px;font-family:inherit;margin-bottom:16px}
svg{overflow:visible}
.bar{fill:#4fc3f7}.bar:hover{fill:#e94560}
.hidden{display:none}
#live-indicator{width:8px;height:8px;border-radius:50%;background:#4caf50;display:inline-block;margin-left:8px}
#live-indicator.disconnected{background:#f44336}
</style>
</head>
<body>
<nav>
<span class="brand">sw dashboard</span>
<a href="#/">Overview</a>
<a href="#/search">Search</a>
<a href="#/analytics">Analytics</a>
<span id="live-indicator" title="WebSocket status"></span>
</nav>
<div class="container" id="app"></div>

<script>
const API='/api/v1/';
let ws=null,wsRetry=0,apiKey='';

async function ensureAuth(){
  const r=await fetch(API+'projects');
  if(r.status===401){apiKey=prompt('API key required:')||''}
}

function $(sel){return document.querySelector(sel)}
function $$(sel){return document.querySelectorAll(sel)}
function h(tag,attrs,children){
  const el=document.createElement(tag);
  if(attrs)Object.entries(attrs).forEach(([k,v])=>{if(k==='class')el.className=v;else if(k.startsWith('on'))el.addEventListener(k.slice(2),v);else el.setAttribute(k,v)});
  if(children){if(typeof children==='string')el.textContent=children;else if(Array.isArray(children))children.forEach(c=>{if(c)el.appendChild(typeof c==='string'?document.createTextNode(c):c)})}
  return el;
}

async function api(path){
  const opts=apiKey?{headers:{'Authorization':'Bearer '+apiKey}}:{};
  const r=await fetch(API+path,opts);
  if(r.status===401){apiKey=prompt('API key required:')||'';return api(path)}
  if(!r.ok)return null;
  return r.json();
}

function svgBar(data,w=400,barH=20){
  if(!data.length)return h('span',{},'No data');
  const max=Math.max(...data.map(d=>d.value),1);
  const ns='http://www.w3.org/2000/svg';
  const svg=document.createElementNS(ns,'svg');
  svg.setAttribute('width',w);svg.setAttribute('height',data.length*(barH+4));
  data.forEach((d,i)=>{
    const bw=Math.max((d.value/max)*(w-120),2);
    const g=document.createElementNS(ns,'g');
    const rect=document.createElementNS(ns,'rect');
    rect.setAttribute('x',100);rect.setAttribute('y',i*(barH+4));
    rect.setAttribute('width',bw);rect.setAttribute('height',barH);
    rect.setAttribute('class','bar');rect.setAttribute('rx',3);
    const label=document.createElementNS(ns,'text');
    label.setAttribute('x',0);label.setAttribute('y',i*(barH+4)+14);
    label.setAttribute('fill','#888');label.setAttribute('font-size','11');
    label.setAttribute('font-family','monospace');
    label.textContent=d.label.slice(0,12);
    const val=document.createElementNS(ns,'text');
    val.setAttribute('x',105+bw);val.setAttribute('y',i*(barH+4)+14);
    val.setAttribute('fill','#e0e0e0');val.setAttribute('font-size','11');
    val.setAttribute('font-family','monospace');
    val.textContent=typeof d.value==='number'?d.value.toFixed(2):d.value;
    g.append(label,rect,val);svg.append(g);
  });
  return svg;
}

async function renderOverview(){
  const app=$('#app');app.innerHTML='';
  const projects=await api('/projects')||[];
  const metrics=await api('/metrics/costs')||{total_cost:0};
  const stats=h('div',{class:'card'},[
    h('div',{class:'stat'},[h('span',{class:'label'},'Projects'),h('div',{class:'value'},String(projects.length))]),
    h('div',{class:'stat'},[h('span',{class:'label'},'Total Cost'),h('div',{class:'value'},'$'+(metrics.total_cost||0).toFixed(2))]),
  ]);
  app.append(stats);
  const grid=h('div',{class:'grid'});
  for(const p of projects){
    const card=h('div',{class:'card'},[
      h('h3',{},h('a',{href:'#/project/'+p.name},p.name)),
      h('div',{class:'stat'},[h('span',{class:'label'},'Path'),h('div',{},p.path)]),
    ]);
    grid.append(card);
  }
  app.append(grid);
  if(metrics.cost_by_run&&metrics.cost_by_run.length){
    const chartCard=h('div',{class:'card'},[h('h3',{},'Cost by Run')]);
    chartCard.append(svgBar(metrics.cost_by_run.map(r=>({label:r.run_id,value:r.cost}))));
    app.append(chartCard);
  }
}

async function renderProject(name){
  const app=$('#app');app.innerHTML='';
  const projects=await api('/projects')||[];
  const proj=projects.find(p=>p.name===name);
  if(!proj){app.innerHTML='<div class="card">Project not found</div>';return}
  const runs=await api('/runs?project_id='+proj.id)||[];
  app.append(h('div',{class:'card'},[h('h3',{},'Project: '+name),h('div',{},'Path: '+proj.path)]));
  const tbl=h('table',{},[
    h('thead',{},[h('tr',{},[h('th',{},'Run ID'),h('th',{},'Status'),h('th',{},'Cost'),h('th',{},'Milestones')])]),
  ]);
  const tbody=h('tbody');
  for(const r of runs){
    const cls=r.status==='complete'?'status-ok':r.status==='failed'?'status-fail':'status-run';
    tbody.append(h('tr',{},[
      h('td',{},h('a',{href:'#/run/'+r.id},r.run_id)),
      h('td',{class:cls},r.status),
      h('td',{},'$'+(r.total_cost_usd||0).toFixed(2)),
      h('td',{},String(r.milestone_count||0)),
    ]));
  }
  tbl.append(tbody);app.append(h('div',{class:'card'},[h('h3',{},'Runs'),tbl]));
}

async function renderSearch(){
  const app=$('#app');app.innerHTML='';
  const card=h('div',{class:'card'},[h('h3',{},'Event Search')]);
  const input=h('input',{class:'search-bar',placeholder:'Filter by event type...',type:'text'});
  const results=h('div',{id:'search-results'});
  input.addEventListener('input',async()=>{
    const q=input.value.trim();
    const events=await api('/events'+(q?'?type='+encodeURIComponent(q):'?limit=50'))||[];
    results.innerHTML='';
    const tbl=h('table',{},[h('thead',{},[h('tr',{},[h('th',{},'Type'),h('th',{},'Milestone'),h('th',{},'Time')])])]);
    const tbody=h('tbody');
    events.forEach(e=>{tbody.append(h('tr',{},[h('td',{},e.event_type),h('td',{},e.milestone_name||'-'),h('td',{},e.timestamp||'-')]))});
    tbl.append(tbody);results.append(tbl);
  });
  card.append(input,results);app.append(card);
  input.dispatchEvent(new Event('input'));
}

async function renderAnalytics(){
  const app=$('#app');app.innerHTML='';
  const models=await api('/metrics/models')||{models:[]};
  const quality=await api('/metrics/quality')||{gap_reports:[]};
  const mCard=h('div',{class:'card'},[h('h3',{},'Model Usage')]);
  if(models.models&&models.models.length){
    mCard.append(svgBar(models.models.map(m=>({label:m.model,value:m.total_cost}))));
  }else{mCard.append(h('div',{},'No model data'))}
  app.append(mCard);
  const qCard=h('div',{class:'card'},[h('h3',{},'Quality Trends')]);
  if(quality.gap_reports&&quality.gap_reports.length){
    qCard.append(svgBar(quality.gap_reports.map((g,i)=>({label:'Pass '+g.pass_num,value:g.critical+g.important}))));
  }else{qCard.append(h('div',{},'No quality data'))}
  app.append(qCard);
}

function route(){
  const hash=location.hash||'#/';
  $$('nav a').forEach(a=>a.classList.toggle('active',a.getAttribute('href')===hash));
  if(hash==='#/'||hash==='')renderOverview();
  else if(hash.startsWith('#/project/'))renderProject(decodeURIComponent(hash.slice(10)));
  else if(hash==='#/search')renderSearch();
  else if(hash==='#/analytics')renderAnalytics();
  else renderOverview();
}

function connectWs(){
  const proto=location.protocol==='https:'?'wss:':'ws:';
  const url=proto+'//'+location.host+'/ws/live'+(apiKey?'?key='+encodeURIComponent(apiKey):'');
  ws=new WebSocket(url);
  ws.onopen=()=>{$('#live-indicator').classList.remove('disconnected');wsRetry=0};
  ws.onclose=()=>{$('#live-indicator').classList.add('disconnected');setTimeout(connectWs,Math.min(1000*Math.pow(2,wsRetry++),30000))};
  ws.onmessage=(e)=>{try{route()}catch(err){}};
}

window.addEventListener('hashchange',route);
window.addEventListener('load',()=>{route();connectWs()});
</script>
</body>
</html>"""
