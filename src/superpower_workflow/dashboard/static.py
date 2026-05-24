from __future__ import annotations

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>sw dashboard</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Menlo','Consolas','Courier New',monospace;background:#1a1a2e;color:#e0e0e0;padding:24px;max-width:900px;margin:0 auto}
h1{color:#7b68ee;font-size:18px;margin-bottom:20px;display:flex;align-items:center;gap:10px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px}
.card{background:#16213e;border:1px solid #2a2a4a;border-radius:6px;padding:14px}
.card h2{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}
.card .value{font-size:22px;color:#fff}
.progress-bar{background:#2a2a4a;border-radius:4px;height:20px;overflow:hidden;margin-top:8px}
.progress-fill{background:linear-gradient(90deg,#7b68ee,#a78bfa);height:100%;transition:width 0.5s ease}
.ms-list{max-height:300px;overflow-y:auto}
.ms{padding:8px 10px;border-bottom:1px solid #1a1a2e;display:flex;justify-content:space-between;font-size:13px}
.ms.completed{color:#4ade80}.ms.failed{color:#f87171}.ms.current{color:#fbbf24}.ms.pending{color:#555}
.ms .cost{color:#888;font-size:12px}
#dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#555}
#dot.running{background:#4ade80;animation:pulse 1.5s infinite}
#dot.completed{background:#4ade80}#dot.failed{background:#f87171}#dot.idle{background:#555}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.quality{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:16px}
</style>
</head>
<body>
<h1><span id="dot"></span> sw dashboard</h1>
<div class="grid">
  <div class="card"><h2>Progress</h2><div id="progress" class="value">0 / 0</div>
    <div class="progress-bar"><div id="bar" class="progress-fill" style="width:0%"></div></div></div>
  <div class="card"><h2>Total Cost</h2><div id="cost" class="value">$0.00</div></div>
  <div class="card"><h2>Elapsed</h2><div id="elapsed" class="value">-</div></div>
  <div class="card"><h2>Current Phase</h2><div id="current" class="value">-</div></div>
</div>
<div class="card">
  <h2>Milestones</h2>
  <div id="milestones" class="ms-list"></div>
</div>
<div class="quality">
  <div class="card"><h2>Rework Rate</h2><div id="rework" class="value">0%</div></div>
  <div class="card"><h2>Defect Density</h2><div id="defects" class="value">0%</div></div>
  <div class="card"><h2>Cost / Task</h2><div id="cpt" class="value">$0.00</div></div>
</div>
<script>
function fmt(s){var m=Math.floor(s/60),sec=Math.floor(s%60);return m>0?m+'m '+sec+'s':sec+'s'}
function update(d){
  document.getElementById('dot').className=d.status||'idle';
  document.getElementById('progress').textContent=d.milestones_completed+' / '+d.milestones_total;
  var pct=d.milestones_total>0?(d.milestones_completed/d.milestones_total*100):0;
  document.getElementById('bar').style.width=pct+'%';
  document.getElementById('cost').textContent='$'+d.total_cost_usd.toFixed(2);
  document.getElementById('elapsed').textContent=d.elapsed_seconds>0?fmt(d.elapsed_seconds):'-';
  document.getElementById('current').textContent=d.current_milestone?d.current_milestone+' > '+d.current_phase:'-';
  document.getElementById('rework').textContent=(d.rework_rate*100).toFixed(1)+'%';
  document.getElementById('defects').textContent=(d.defect_density*100).toFixed(1)+'%';
  document.getElementById('cpt').textContent='$'+d.cost_per_task.toFixed(2);
  var el=document.getElementById('milestones');
  el.textContent='';
  function addMs(cls,prefix,name,extra){
    var row=document.createElement('div');row.className='ms '+cls;
    var sp=document.createElement('span');sp.textContent=prefix+' '+name;row.appendChild(sp);
    if(extra){var sp2=document.createElement('span');sp2.className='cost';sp2.textContent=extra;row.appendChild(sp2);}
    el.appendChild(row);
  }
  var done=new Set(d.completed||[]),fail=new Set(d.failed||[]),skip=new Set(d.skipped||[]);
  (d.milestone_names||[]).forEach(function(m){
    var c=d.cost_by_milestone&&d.cost_by_milestone[m];
    if(done.has(m)){addMs('completed','+',m,c?'$'+c.toFixed(2):'');}
    else if(m===d.current_milestone){addMs('current','>',m,d.current_phase);}
    else if(fail.has(m)){addMs('failed','x',m,'');}
    else if(skip.has(m)){addMs('pending','-',m,'');}
    else{addMs('pending','.',m,'');}
  });
}
fetch('/api/snapshot').then(function(r){return r.json()}).then(update).catch(function(){});
var es=new EventSource('/api/events');
es.onmessage=function(e){try{update(JSON.parse(e.data))}catch(x){}};
</script>
</body>
</html>
"""
