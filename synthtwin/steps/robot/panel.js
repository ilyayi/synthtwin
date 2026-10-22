/* The robot step's panel: the protocol package that went to the self-building
   lab (conditions, materials, equipment and tools, measurements with their
   acceptance bands, steps), and the feedback window that waits for the
   researcher's results (every run kept, measured vs predicted). esc, fmt and
   the shell styles come from common.js / agent.css. */
/* ---- robot */
const rbUnit=u=>({um:'µm',uL:'µL',ul:'µL',C:'°C'}[u]||u||'');
const rbBand=b=>b&&b.low!=null?`${fmt(b.low)}–${fmt(b.high)}`:'—';
function rbTarget(t){if(!t)return'—';return t.value!=null?`${fmt(t.value)}`:t.max!=null&&t.min!=null?`${fmt(t.min)}–${fmt(t.max)}`:t.max!=null?`≤ ${fmt(t.max)}`:t.min!=null?`≥ ${fmt(t.min)}`:'—'}
/* studies sent before packages existed: the same sections, read off the request */
function rbLegacy(s,r){const p=r.proposal,pb=s.problem||{},rc=r.recipe||{};
  return {request:p.id,label:r.label,synthesis:{title:rc.title||pb.title||'',material:pb.material||'',method:p.method||pb.method||''},
    conditions:Object.entries(p.conditions||{}).map(([k,v])=>({name:k,label:k.replace(/_/g,' '),value:v,unit:'',kind:k in(pb.knobs||{})?'varied':'fixed'})),
    materials:rc.materials||[],equipment:rc.equipment||[],tools:[],
    measurements:Object.keys(pb.targets||{}).map(q=>({quantity:q,label:q.replace(/_/g,' '),unit:(p.predicted[q]||{}).unit||'',target:pb.targets[q],predicted:p.predicted[q]||null,instrument:''})),
    steps:(rc.steps||p.steps||[]).map(x=>x.replace(/^\s*\d+[.)]\s*/,'')),acceptance:rc.checks||[]}}
function rbPackage(s,r,pk){const sec=(t,b,n)=>`<div class="rb-sec"><h5>${t}${n?` <span class="rb-n">${n}</span>`:''}</h5>${b}</div>`;
  const src=x=>x==='from the steps'?' <span class="rb-src">read off the steps; confirm</span>':'';const busy=s.busy&&/material|equipment/.test(s.busy);
  const cond=`<table class="rb-tab">${pk.conditions.map(c=>`<tr class="${c.kind}"><td>${esc(c.label)}</td><td class="v">${fmt(c.value)} <span class="u">${esc(rbUnit(c.unit))}</span></td><td><span class="rb-k ${c.kind}">${c.kind==='varied'?'chosen':'fixed'}</span></td></tr>`).join('')}</table>`;
  const mats=pk.materials.length?`<ul class="rb-list">${pk.materials.map(m=>`<li><b>${esc(m.name)}</b>${m.amount?` <span class="v">${esc(m.amount)}</span>`:''}${m.role?` <span class="rb-role">${esc(m.role)}</span>`:''}</li>`).join('')}</ul>`:`<p class="help" style="margin:0">${busy?'<span class="spin"></span> The agent is listing them from the recipe.':'Not listed in the recipe; the lab reads them off the steps.'}</p>`;
  const eq=`<div class="rb-chips">${pk.equipment.map(x=>`<span class="rb-chip">${esc(x)}</span>`).join('')}${(pk.tools||[]).filter(x=>!pk.equipment.includes(x)).map(x=>`<span class="rb-chip meas">${esc(x)}</span>`).join('')}</div>`;
  const meas=`<table class="rb-tab meas"><tr><th>measure</th><th>with</th><th>target</th><th>predicted band</th></tr>${pk.measurements.map(m=>`<tr><td>${esc(m.label)} <span class="u">${esc(rbUnit(m.unit))}</span></td><td class="ins">${esc(m.instrument||'—')}</td><td class="v">${rbTarget(m.target)}</td><td class="v">${m.predicted?`${fmt(m.predicted.value)} <span class="u">[${rbBand(m.predicted)}]</span>`:'—'}</td></tr>`).join('')}</table>
    ${(pk.acceptance||[]).length?`<details class="rb-acc"><summary>Acceptance checks (${pk.acceptance.length})</summary><ul>${pk.acceptance.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`:''}`;
  return `<div class="abox rb-pkg">
    <div class="rb-head"><div><p class="rb-eyebrow">Protocol package · request ${esc(String(pk.request||r.proposal.id).split('-').pop())} <span class="pill ${r.label==='exploratory'?'web':'blind'}">${esc(r.label)}</span></p>
      <h4>${esc(pk.synthesis.title||pk.synthesis.material)}</h4><p class="rb-meth">${esc(pk.synthesis.material)} · ${esc(pk.synthesis.method)}</p></div>
      ${s.phases.robot.package?`<a class="btn ghost small" href="/api/agent/${esc(s.id)}/package" download>Download JSON</a>`:''}</div>
    <div class="rb-cols">${sec('Conditions',cond)}${sec('Materials'+src(pk.materials_source),mats,pk.materials.length||'')}</div>
    ${sec('Equipment and tools'+src(pk.equipment_source),eq)}
    ${sec('Measurements and acceptance',meas)}
    <details class="rb-sec rb-steps"><summary><h5>Steps <span class="rb-n">${pk.steps.length}</span></h5></summary><ol>${pk.steps.map(x=>`<li>${esc(x)}</li>`).join('')}</ol></details>
    <p class="help" style="margin:0">Saved as robot_requests/${esc(r.proposal.id)}${s.phases.robot.package?'.package':''}.json · the lab maps it onto its own hardware; its capability list never filters it</p></div>`}
function rbRun(x,pk){const ml=q=>pk.measurements.find(m=>m.quantity===q)||{label:q.replace(/_/g,' '),unit:''};const b=x.rows.filter(r=>r.inside!=null),n=b.filter(r=>r.inside).length;
  return `<div class="rb-run"><p class="rb-rh"><b>Run ${x.n}</b> <span>${new Date(x.at*1000).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'})}</span>${b.length?`<span class="pill ${n===b.length?'blind':'off'}">${n} of ${b.length} inside the band</span>`:''}</p>
    <table class="rb-tab"><tr><th>quantity</th><th>measured</th><th>predicted</th><th></th></tr>${x.rows.map(r=>`<tr><td>${esc(ml(r.quantity).label)} <span class="u">${esc(rbUnit(ml(r.quantity).unit))}</span></td><td class="v">${fmt(r.measured)}</td><td class="v">${r.predicted?`${fmt(r.predicted.value)} <span class="u">[${rbBand(r.predicted)}]</span>`:'—'}</td><td>${r.inside==null?'<span class="pill p">no band</span>':r.inside?'<span class="pill blind">inside</span>':'<span class="pill off">outside</span>'}</td></tr>`).join('')}</table>
    ${x.notes?`<p class="rb-notes">${esc(x.notes)}</p>`:''}</div>`}
function pRobot(s,P){const r=P.request;if(!r)return wait('');const p=r.proposal;const pk=P.package||rbLegacy(s,r);
  const runs=P.runs||(P.results?[{n:1,at:r.at,rows:P.results,notes:''}]:[]);
  const qs=[...new Set([...pk.measurements.map(m=>m.quantity),...((s.problem.system||'colloid')==='colloid'?['lspr_nm','dls_z_nm','dls_pdi']:[])])];
  const munit=q=>rbUnit((pk.measurements.find(m=>m.quantity===q)||{}).unit||(p.predicted[q]||{}).unit||'');
  const form=`<div class="rb-form">${qs.map(q=>`<label class="rb-in"><span>${esc((pk.measurements.find(m=>m.quantity===q)||{label:q.replace(/_/g,' ')}).label)} <span class="u">${esc(munit(q))}</span>${p.predicted[q]?`<em>predicted ${fmt(p.predicted[q].value)} [${rbBand(p.predicted[q])}]</em>`:''}</span><input type="number" step="any" data-mq="${q}" placeholder="—"></label>`).join('')}
    <label class="rb-in wide"><span>Notes <em>run conditions, anything that went off-plan</em></span><textarea id="agnotes" rows="2"></textarea></label>
    <button class="btn cu small" type="button" id="agres">${runs.length?'Record another run':'Record the results'}</button></div>`;
  return `<div class="apanel robot"><h3>Robot</h3><p class="sub">The package goes to the self-building lab: what to make, the conditions, the materials, the equipment and tools, and what to measure. The lab runs it on its own hardware; you send the measurements back here.</p>
   <div class="rb-grid"><div class="abox rb-fb">${runs.length?`<div class="rb-runs"><h4>Results <span class="rb-n">${runs.length} run${runs.length>1?'s':''}</span></h4>${runs.slice().reverse().map(x=>rbRun(x,pk)).join('')}</div>`
      :`<div class="rb-wait"><span class="rb-dot"></span><div><h4>Waiting for your results</h4><p>The package is with the lab. When the run is done, enter what it measured; I compare it with the predicted band and add the run to the library, so the next study calibrates on it.</p></div></div>`}
     <div>${runs.length?'<h5 class="rb-again">Another run</h5>':''}${form}</div></div>
    ${rbPackage(s,r,pk)}</div></div>`}


STEP_PANELS.robot = pRobot;
