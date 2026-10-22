/* The bench step's panel: what the builder built and its QA review, the
   verdict cards per variant, and per-study charts (prediction vs measurement,
   MAE vs the null floor). AG, wait, esc, fmt and the charts come from
   agent.js / common.js. */
const VCOL={null:'#77756f',model:'#62c6f2',uncalibrated:'#62c6f2',calibrated:'#d8894f',atomistic:'#4fd39a'};

/* ---- benchmark */
function buildBox(b){if(!b)return '';const r=b.report||{};const ms=r.methods||[];
  return `<div class="abox" style="margin-bottom:14px"><h4>What was built ${b.check.ok?'<span class="pill blind">passes its contract check</span>':'<span class="pill off">contract check fails</span>'} <span class="help">${fmt((b.seconds||0)/60)} min${b.cost_usd!=null?' · $'+fmt(b.cost_usd):''}</span></h4>
   ${r.model?`<p>${esc(r.model)}</p>`:''}
   ${ms.length?`<table class="mtab"><tr><th>method</th><th>status</th><th>what it gave</th></tr>${ms.map(m=>`<tr><td>${esc(m.name||m.id)}</td><td><span class="pill ${m.status==='ran'?'blind':m.status==='skipped'?'off':'web'}">${esc(m.status||'')}</span></td><td>${esc(m.what||'')}${m.values&&Object.keys(m.values).length?mvals(m.values):''}</td></tr>`).join('')}</table>`:''}
   ${(r.limits||[]).length?`<p class="help"><b>Limits:</b> ${esc(r.limits.join(' · '))}</p>`:''}
   ${b.check.ok?'':`<pre class="help" style="white-space:pre-wrap">${esc(b.check.out)}</pre>`}${qaBox(b.qa,b.qa_rounds)}</div>`}
const QCOL={pass:'blind',fix:'web',fail:'off',skipped:'off'};
function qaBox(q,n){if(!q)return '';
  return `<div style="margin-top:12px"><h4>QA review <span class="pill ${QCOL[q.overall]}">${esc(q.overall)}</span> <span class="help">${n||1} round${n>1?'s':''}</span></h4><p>${esc(q.summary||'')}</p>
   <table class="mtab"><tr><th>method</th><th>verdict</th><th>checks</th></tr>${(q.methods||[]).map(m=>`<tr><td>${esc(m.id)}</td><td><span class="pill ${QCOL[m.verdict]||''}">${esc(m.verdict)}</span></td><td>${(m.checks||[]).map(c=>`<div>${c.ok?'✓':'✗'} <b>${esc(c.name)}</b> <span class="help">${esc(c.evidence)}</span></div>`).join('')}${(m.fixes||[]).length?`<div class="help">open: ${esc(m.fixes.join(' · '))}</div>`:''}</td></tr>`).join('')}
   <tr><td>model.py</td><td><span class="pill ${QCOL[(q.model||{}).verdict]||''}">${esc((q.model||{}).verdict||'')}</span></td><td class="help">${esc(((q.model||{}).issues||[]).join(' · '))}</td></tr></table></div>`}
function progBox(g){if(!g)return '';const js=g.jobs||[];
  return `<div class="abox"><h4>Simulations in progress <span class="help">${esc(g.stage)}${g.round?' · QA round '+g.round:''} · ${fmt(g.minutes||0)} min</span></h4>
   ${js.length?`<table class="mtab"><tr><th>job</th><th>state</th><th>min</th><th>last log line</th></tr>${js.map(j=>`<tr><td>${esc(j.id)}${j.gpu!=null?' <span class="pill">GPU'+j.gpu+'</span>':''}</td><td><span class="pill ${j.state==='done'?'blind':j.state==='running'?'web':'off'}">${esc(j.state)}</span></td><td>${fmt(j.minutes)}</td><td class="help" style="font-family:monospace">${esc(j.tail)}</td></tr>`).join('')}</table>`:'<p class="help">No detached jobs yet; the builder is working in its session.</p>'}
   ${(g.sessions||[]).length?`<p class="help"><b>Builder sessions:</b> ${esc(g.sessions.map(x=>x.why+' ('+fmt(x.minutes)+' min)').join(' → '))}</p>`:''}
   ${(g.qa||[]).map(x=>`<p class="help"><b>QA round ${x.round}: ${esc(x.overall)}</b> — ${esc(x.summary)}</p>`).join('')}</div>`}
function pBench(s,P,live){const S=P.summary;if(!S)return P.build&&!s.busy?`<div class="apanel"><h3>Benchmark</h3>${buildBox(P.build)}</div>`:P.progress?`<div class="apanel"><h3>Building the simulator</h3>${progBox(P.progress)}</div>`:wait(s.busy||'Benchmarking.');
  const vs=S.variants||[];const V=AG.meta.variants||{};
  const cards=vs.map(v=>`<div class="abox ${v===P.variant?'best':''}"><div class="row"><i style="width:10px;height:10px;border-radius:2px;background:${VCOL[v]}"></i><b>${esc(v)}</b></div>
    <span class="big">${S.validated[v]}/${S.n_scored}</span><span class="help" style="margin:0">studies where it got the trend and beat the null floor</span>
    <span class="meta">error / null: ${S.mean_mae_over_null[v]==null?'—':fmt(S.mean_mae_over_null[v])}</span><span class="help" style="margin:0">${esc(V[v]||'')}</span></div>`).join('');
  const cases=(P.cases||[]).filter(c=>c.points&&c.points.length);const ids=cases.map(c=>c.case_id);const cid=ids.includes(AG.ctab)?AG.ctab:ids[0];
  const c=cases.find(x=>x.case_id===cid);
  let detail='';
  if(c){const q=c.quantities[0];const xs=c.points.map(p=>+p.value);
    const ser=['null',...vs].filter(v=>c.points.some(p=>p.pred[v]&&p.pred[v][q])).map(v=>({label:v,color:VCOL[v],band:v!=='null',dash:v==='null',
      pts:c.points.filter(p=>p.pred[v]&&p.pred[v][q]).map(p=>[+p.value,p.pred[v][q].value,p.pred[v][q].low,p.pred[v][q].high])}));
    const meas={label:'measured',color:'#f2f1ed',dots:true,line:false,pts:c.points.filter(p=>p.measured&&p.measured[q]!=null).map(p=>[+p.value,p.measured[q]])};
    const anc=c.points.find(p=>p.label===c.anchor_label);
    const bars=barChart({w:340,h:170,groups:(c.scores||[]).filter(x=>x.quantity===q).map(x=>({label:x.variant,v:x.mae,color:VCOL[x.variant]})),ylab:'MAE '+q});
    const verdict=c.verdict||{};
    detail=`<div class="ctabs" style="margin-top:16px">${cases.map(x=>`<button class="chip ${x.case_id===cid?'on':''}" type="button" data-ct="${esc(x.case_id)}">${esc(x.case_id.startsWith('web-')?'literature '+(+x.case_id.slice(4)+1):x.case_id.startsWith('lib:')?'library: '+x.title.slice(0,24):x.case_id)}</button>`).join('')}</div>
     <p style="margin:4px 0 8px"><b>${esc(c.title)}</b> ${c.blind?'<span class="pill blind">blind: outcomes revealed after scoring</span>':'<span class="pill web">not blind</span>'}</p>
     <div class="charts"><div class="chart"><p class="ct">${esc(q)} vs ${esc(c.sweep_variable)}</p><p class="cs">dots: measured · lines: predicted, shaded: band · ◆ anchor (used for calibration)</p>
       ${lineChart({w:360,h:230,xlab:c.sweep_variable,ylab:q,series:[...ser,meas],marks:[],anchor:anc?+anc.value:null,logx:xs.every(x=>x>0)&&Math.max(...xs)/Math.min(...xs)>15})}${legend([...ser,meas])}</div>
      <div class="chart"><p class="ct">Mean absolute error by variant</p><p class="cs">lower is better; the grey bar is the null floor (anchor everywhere)</p>${bars}
       <p class="cs">${Object.entries(verdict).map(([v,x])=>`${v}: ${x.validated?'validated':'not validated'} (ρ ${x.spearman==null?'—':fmt(x.spearman)})`).join(' · ')}</p></div></div>
     ${(c.notes||[]).length?`<p class="help">${esc(c.notes.join(' · '))}</p>`:''}`}
  const errs=(P.cases||[]).filter(x=>x.error);
  return `<div class="apanel"><h3>Benchmark</h3><p class="sub">${S.n_scored} of ${S.n_cases} studies scored in ${fmt(S.seconds)} s. ${S.trusted?'The stack passes on at least half of them and beats the null floor on average.':'The stack is <b>not</b> trusted (validated on fewer than half, or no better than the null floor on average): your case is exploratory.'}</p>
   ${buildBox(P.build)}<div class="verd">${cards}</div>
   ${live&&vs.length?`<div class="row" style="display:flex;gap:10px;align-items:center"><label class="lbl" for="agvar" style="margin:0">Use for your case</label><select id="agvar">${vs.map(v=>`<option ${v===P.variant?'selected':''}>${v}</option>`).join('')}</select></div>`:''}
   ${detail}${errs.length?`<div class="callout warn" style="margin-top:10px">${esc(errs.map(x=>x.case_id+': '+x.error).join('; '))}</div>`:''}</div>`}
STEP_PANELS.bench = pBench;

/* a method's numbers as a key/value grid; long lists fold after six */
function mvals(v){const e=Object.entries(v).map(([k,x])=>`<span class="k">${esc(k.replace(/_/g,' '))}</span><span class="v">${esc(typeof x==='number'?fmt(x):String(x))}</span>`);
  const g=r=>`<div class="mvals">${r.join('')}</div>`;
  return e.length<=6?g(e):g(e.slice(0,6))+`<details class="more"><summary>${e.length-6} more values</summary>${g(e.slice(6))}</details>`}
