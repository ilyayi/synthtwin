/* The robot step's panel: the request that went to the platform, and the
   measurements the researcher enters (or the recorded results against the
   predicted bands). esc, fmt and the shell styles come from common.js /
   agent.css; the input rows are .mrow from theme.css. */
/* ---- robot */
function pRobot(s,P){const r=P.request;if(!r)return wait('');const p=r.proposal;const qs=[...new Set([...Object.keys(s.problem.targets),...((s.problem.system||'colloid')==='colloid'?['lspr_nm','dls_z_nm','dls_pdi']:[])])];
  return `<div class="apanel"><h3>Robot</h3><p class="sub">${esc(r.handoff)}</p>
   <div class="agrid"><div class="abox"><h4>Request ${esc(p.id.split('-').pop())} <span class="pill ${r.label==='exploratory'?'web':'blind'}">${esc(r.label)}</span></h4>
     ${r.recipe?`<p>${esc(r.recipe.title)}</p>`:''}<div class="row">${Object.entries(p.conditions).map(([k,v])=>`<span class="pill p">${esc(k)}=${fmt(v)}</span>`).join('')}</div>
     <ol style="margin:4px 0 0;padding-left:18px;color:var(--ink2)">${(p.steps||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ol>
     <p class="help" style="margin:0">Saved as robot_requests/${esc(p.id)}.json</p></div>
    <div class="abox"><h4>${P.results?'Measured vs predicted':'Enter the measurements'}</h4>
     ${P.results?`<table class="mtab"><tr><th>quantity</th><th>measured</th><th>predicted</th><th></th></tr>${P.results.map(x=>`<tr><td>${esc(x.quantity)}</td><td>${fmt(x.measured)}</td><td>${x.predicted?fmt(x.predicted.value)+' ['+fmt(x.predicted.low)+'–'+fmt(x.predicted.high)+']':'—'}</td><td>${x.inside==null?'<span class="pill p">no band</span>':x.inside?'<span class="pill blind">inside</span>':'<span class="pill off">outside</span>'}</td></tr>`).join('')}</table>`
      :`${qs.map(q=>`<div class="mrow"><span>${esc(q)}${p.predicted[q]?' <span class="help">(pred. '+fmt(p.predicted[q].value)+')</span>':''}</span><input type="number" step="any" data-mq="${q}"></div>`).join('')}<div><button class="btn cu small" type="button" id="agres">Record the results</button></div>`}</div></div></div>`}


STEP_PANELS.robot = pRobot;
