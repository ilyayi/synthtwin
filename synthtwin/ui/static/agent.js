/* SynthTwin study agent shell: chat, gated phases, the stepper and the study
   panels' plumbing (vanilla JS, inline SVG). Shared helpers ($, esc, api, post,
   fmt, icon, the charts) come from common.js; each step's panel lives in its
   step folder, served concatenated as /static/steps.js, and registers itself
   into STEP_PANELS. */
const AG={meta:null,sid:null,view:null,s:null,poll:null,qtab:null,ktab:null,ctab:null,viz:null,vtab:{},vkey:null};
const GATE={goal:['Confirm the goal','Then I look for related studies (benchmark cases, library, literature).'],
  prior:['Choose simulations','Next: which methods to run, with time and the insight each gives.'],
  stack:['Use this stack','Next: pick related studies to benchmark it on.'],
  sample:['Run the benchmark','The stack predicts these studies; blind ones are scored against sealed data.'],
  bench:['Approve: simulate my case','Maps, sensitivities and the optimiser on your goal (1-2 min).'],
  case:['Write the recipe',''],
  recipe:['Send to the robot','Writes a protocol package for a self-building lab; measurements come back here.']};

async function agentMeta(){if(!AG.meta)AG.meta=await api('/api/agent');return AG.meta}

/* ---------------------------------------------------------------- home: start box */
const EXAMPLES=['I need gold nanoparticles around 15 nm with a narrow size distribution for a DLS standard.',
  'Silver colloid with the LSPR peak near 400 nm, as monodisperse as the robot can make it.',
  'Seeded growth of Au to 40 nm: which seed-to-gold ratio and temperature?'];
function agentStartHtml(){return `<div class="astart">
  <h2 style="margin:0;font-size:clamp(26px,3vw,38px)">Tell the agent your problem.</h2>
  <p class="lede" style="margin:0">It will agree a measurable goal with you, show what related studies swept and found, propose a simulation stack with time and insight, test it on known results, simulate your case and suggest a recipe for the robot. You confirm every step.</p>
  <textarea id="aq" placeholder="What do you want to make, and what matters about it?"></textarea>
  <div class="ex">${EXAMPLES.map(e=>`<button class="chip" type="button" data-ex="${esc(e)}">${esc(e)}</button>`).join('')}</div>
  <p class="err" id="aerr"></p>
  <div><button class="btn cu big" type="button" id="ago">Start the conversation</button></div></div>`}
function bindAgentStart(){const b=$('#ago');if(!b)return;
  document.querySelectorAll('[data-ex]').forEach(c=>c.onclick=()=>{$('#aq').value=c.dataset.ex;$('#aq').focus()});
  b.onclick=async()=>{const t=$('#aq').value.trim();if(!t){$('#aerr').textContent='Describe your problem first.';return}
    b.disabled=true;b.innerHTML='<span class="spin"></span>Starting';
    try{const r=await post('/api/agent',{text:t});location.hash='#/s/'+r.id}catch(e){$('#aerr').textContent=e.message;b.disabled=false;b.textContent='Start the conversation'}}}
function agentCard(s){const ph=AG.meta?.steps||[];const cur=ph.findIndex(p=>p.id===s.phase);
  const st=s.busy?'running':s.status==='complete'?'complete':'awaiting_user';
  return `<button class="scard" type="button" onclick="location.hash='#/s/${esc(s.id)}'">
   <div class="row"><span class="status ${st}">${esc(s.busy?'working':s.status==='complete'?'complete':'needs you')}</span>${s.material?`<span class="pill">${esc(s.material)}</span>`:''}<span class="pill">agent</span></div>
   <h4>${esc(s.title)}</h4><p>${esc(s.text||'')}</p>
   <div class="strip">${ph.map((p,i)=>`<i class="${i<cur||s.status==='complete'?'done':i===cur?(s.busy?'running':'awaiting_user'):''}" title="${esc(p.name)}"></i>`).join('')}</div>
   <div class="striplab">${ph.map(p=>`<span>${esc(p.id[0].toUpperCase()+p.id.slice(1))}</span>`).join('')}</div>
   <span class="meta">${new Date(s.created*1000).toLocaleString()} · ${esc((ph[cur]||{}).name||'')}</span></button>`}

/* ---------------------------------------------------------------- study page */
async function agentStudy(id,s){await agentMeta();
  if(AG.viz===null)api('/api/viz').then(v=>{AG.viz=v;if(AG.s&&AG.s.id===id)render(AG.s)}).catch(()=>{AG.viz={enabled:false,items:[]}});
  if(AG.sid!==id||!$('#agmain')){AG.sid=id;AG.view=null;
    $('#app').innerHTML=`<div class="wrap"><div class="shead" style="padding-bottom:4px"><a class="back" href="#/">← All studies</a></div>
     <div class="ag"><div class="ag-main" id="agmain"></div>
     <aside class="chat"><div class="ch"><span class="orb"></span><b>SynthTwin agent</b><span class="meta" id="agllm" style="margin-left:auto"></span></div>
      <div class="log" id="aglog"></div><div class="gate" id="aggate"></div>
      <form id="agform"><textarea id="agin" placeholder="Reply, ask, or tell it what to change…"></textarea><button class="btn cu" type="submit">Send</button></form></aside></div></div>`;
    $('#agform').onsubmit=async e=>{e.preventDefault();const t=$('#agin').value.trim();if(!t)return;
      try{await post(`/api/agent/${id}/chat`,{text:t});$('#agin').value='';refresh()}catch(err){toast(err.message)}};
    $('#agin').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();$('#agform').requestSubmit()}}}
  if(AG.want){AG.view=AG.want;AG.want=null}
  render(s)}
async function refresh(){if(!AG.sid)return;try{const s=await api('/api/studies/'+encodeURIComponent(AG.sid));render(s)}catch(e){}}
function toast(m){const g=$('#aggate');if(g)g.insertAdjacentHTML('afterbegin',`<p class="err" style="margin:0 0 8px">${esc(m)}</p>`)}

/* light markdown for chat: bold, inline code, bullets (the bubble keeps line breaks) */
function chatMd(t){return esc(t).replace(/\*\*([^*\n]+)\*\*/g,'<b>$1</b>').replace(/`([^`\n]+)`/g,'<code>$1</code>').replace(/^(\s*)[-*] /gm,'$1• ')}
function render(s){const prev=AG.s;AG.s=s;
  const ph=AG.meta.steps,cur=s.phase,ci=ph.findIndex(p=>p.id===cur);
  const view=AG.view&&ph.findIndex(p=>p.id===AG.view)<=ci?AG.view:cur;
  // chat
  const log=$('#aglog');const atBottom=log.scrollHeight-log.scrollTop-log.clientHeight<40;
  let lastPh=null;const rows=[];
  for(const m of s.chat){const r=rows[rows.length-1];if(r&&r.m.role===m.role&&r.m.phase===m.phase&&r.m.text===m.text)r.n++;else rows.push({m,n:1})}
  log.innerHTML=rows.map(({m,n})=>{let d='';if(m.phase!==lastPh){lastPh=m.phase;d=`<div class="pdiv">${esc((ph.find(p=>p.id===m.phase)||{}).name||m.phase)}</div>`}
    return d+`<div class="msg ${m.role}">${chatMd(m.text)}${n>1?`<span class="rep">×${n}</span>`:''}</div>`}).join('')
    +(s.busy?`<div class="typing"><span class="spin"></span>${esc(s.busy)}…</div>`:'');
  if(atBottom||!prev||prev.chat.length!==s.chat.length||!!prev.busy!==!!s.busy)log.scrollTop=log.scrollHeight;
  const last=[...s.chat].reverse().find(m=>m.meta&&m.meta.cost_usd!=null);
  $('#agllm').textContent=last?`${(last.meta.ms/1000).toFixed(0)} s / turn`:'';
  // gate
  const g=GATE[cur];const P=s.phases[cur];
  $('#aggate').innerHTML=s.error?`<p class="err" style="margin:0 0 8px">${esc(s.error)}</p><button class="btn ghost" type="button" id="agretry">Retry this step</button>`
    :s.busy||!g||cur==='case'?`<p class="help" style="margin:0">${s.busy?'The agent is working; you can read the panels meanwhile.':cur==='robot'?'Enter the robot\'s measurements in the Robot panel.':''}</p>`
    :`<button class="btn ${P.ready?'cu':'ghost'}" type="button" id="agok">${esc(g[0])}</button><p class="help">${esc(g[1])}${P.ready?'':' The agent has not marked this step ready; you can still confirm.'}</p>`;
  $('#agretry')&&($('#agretry').onclick=()=>post(`/api/agent/${s.id}/retry`,{}).then(refresh).catch(e=>toast(e.message)));
  $('#agok')&&($('#agok').onclick=async()=>{const b=$('#agok');b.disabled=true;b.innerHTML='<span class="spin"></span>'+esc(g[0]);
    const body={phase:cur};
    if(cur==='stack')body.selected=[...document.querySelectorAll('[data-m]:checked')].map(i=>i.dataset.m);
    if(cur==='sample'){body.selected=[...document.querySelectorAll('[data-c]:checked')].map(i=>i.dataset.c);if(!body.selected.length)body.skip=true}
    if(cur==='bench'&&$('#agvar'))body.variant=$('#agvar').value;
    if(cur==='recipe'){const r=document.querySelector('[name=agprop]:checked');if(r)body.proposal_id=r.value}
    try{await post(`/api/agent/${s.id}/confirm`,body);AG.view=null;refresh()}catch(e){toast(e.message);b.disabled=false;b.textContent=g[0]}});
  // main
  const keep=document.activeElement&&$('#agmain').contains(document.activeElement)&&document.activeElement.matches('input,select,textarea');
  if(!keep||!prev||prev.phase!==s.phase){
    const pb=s.problem||{};
    $('#agmain').innerHTML=`<div class="ag-head"><p class="eyebrow">Agent study${pb.material?' · '+esc(pb.material):''}${pb.method?' · '+esc(pb.method):''}</p>
      <h2>${esc(s.title)}</h2><p class="help">${esc(s.text)}</p></div>
     <div class="psteps">${ph.map((p,i)=>{const cls=i<ci||s.status==='complete'?'done':i===ci?(s.busy?'busy':'cur'):'pending';
       const word=cls==='done'?'done':cls==='busy'?'working':cls==='cur'?'needs you':'';
       return `<button class="pst ${cls} ${p.id===view?'view':''}" type="button" data-v="${p.id}" ${i>ci?'disabled':''} title="${esc(p.short)}"><span class="pi">${cls==='done'?icon('check'):icon(p.icon||p.id)}</span><b>${esc(p.name)}</b><span class="ss">${esc(p.short)}</span><span class="s">${cls==='busy'?'<span class="spin"></span>':''}${word}</span></button>`}).join('')}</div>
     ${panel(s,view)}`;
    document.querySelectorAll('.pst[data-v]').forEach(b=>b.onclick=()=>{AG.view=b.dataset.v;render(AG.s)});
    bindPanel(s,view)}
  clearTimeout(AG.poll);if(s.busy)AG.poll=setTimeout(()=>{if(location.hash.startsWith('#/s/'+s.id))refresh()},1500)}

/* each phase in one line for the researcher: what happens there, what they do
   (from the steps' step.json, served by /api/agent) */
const phaseProtocols=ph=>((AG.meta&&AG.meta.protocols)||[]).filter(p=>(p.phases||[]).includes(ph));
const phaseStrip=ph=>{const st=((AG.meta&&AG.meta.steps)||[]).find(x=>x.id===ph);if(!st)return'';
  return `<div class="pstrip">${icon(st.icon||ph,'lg')}<div>
  <span><b>What happens here</b> ${esc(st.what_happens)}</span>
  <span><b>What you do</b> ${esc(st.what_you_do)}</span>
  ${phaseProtocols(ph).length?`<span class="pproto"><b>Protocol</b> ${phaseProtocols(ph).map(p=>
    `<i title="${esc(p.purpose||'')}">${esc(p.name)} <em>v${esc(p.version)}</em></i>`).join('')}</span>`:''}</div></div>`}

function panel(s,ph){const f=STEP_PANELS[ph];
  return phaseStrip(ph)+(f?f(s,s.phases[ph]||{},ph===s.phase):'')}
function bindPanel(s,ph){
  document.querySelectorAll('[data-qt]').forEach(b=>b.onclick=()=>{AG.qtab=b.dataset.qt;render(AG.s)});
  document.querySelectorAll('[data-kt]').forEach(b=>b.onclick=()=>{AG.ktab=b.dataset.kt;render(AG.s)});
  document.querySelectorAll('[data-ct]').forEach(b=>b.onclick=()=>{AG.ctab=b.dataset.ct;render(AG.s)});
  document.querySelectorAll('[data-m],[data-c]').forEach(i=>i.onchange=()=>i.closest('.abox,tr')?.classList.toggle('sel',i.checked));
  document.querySelectorAll('[data-slink]').forEach(b=>{b.onclick=()=>{const el=document.getElementById('cl-'+b.dataset.slink);
    if(!el)return;el.scrollIntoView({behavior:'smooth',block:'center'});
    el.classList.remove('flash');void el.offsetWidth;el.classList.add('flash')};});
  document.querySelectorAll('[data-vtab]').forEach(b=>b.onclick=e=>{e.stopPropagation();const[k,j]=b.dataset.vtab.split(':');AG.vtab[k]=+j;render(AG.s)});
  document.querySelectorAll('[data-viz]').forEach(b=>b.onclick=()=>{const[k]=b.dataset.viz.split(':');lightbox(AG.s,s.phases[ph]||{},k)});
  const rb=$('#agres');rb&&(rb.onclick=async()=>{const m={};document.querySelectorAll('[data-mq]').forEach(i=>{if(i.value!=='')m[i.dataset.mq]=+i.value});
    const nt=$('#agnotes');try{await post(`/api/agent/${s.id}/result`,{measured:m,notes:nt?nt.value:''});refresh()}catch(e){toast(e.message)}})}
const wait=t=>`<div class="apanel"><p class="help" style="display:flex;gap:8px;align-items:center;margin:0"><span class="spin"></span>${esc(t)}</p></div>`;
