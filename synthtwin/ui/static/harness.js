/* SynthTwin harness view (#/harness): the self-improving layer over the step
   protocols. The model stays frozen; per step an overlay (versioned edits,
   adopted only after probing recorded studies) and a lessons library grow at
   test time — reflect writes lessons after each confirmed step, evolve runs
   propose-probe-compose. $, esc, api, post, icon, fmt come from common.js;
   agent.js stamps HV.badge() on the study page's step strip. */
const HV={index:null,poll:null,diff:{a:null,b:null}};

async function hvIndex(){if(!HV.index){try{HV.index=(await api('/api/harness')).steps;
  if(typeof AG!=='undefined'&&AG.s)render(AG.s)}catch(e){HV.index=[]}}return HV.index}

/* the study-page badge: "harness v2 · 3 lessons" on a step of the strip */
HV.badge=function(step){const s=(HV.index||[]).find(x=>x.step===step);
  if(!s||(!s.overlay_version&&!s.lessons))return '';
  return `<span class="hv-b" data-hvb="${esc(step)}" role="link" tabindex="0"
   title="this step runs an evolved harness: overlay${s.overlay_version?' v'+s.overlay_version:''} + ${s.lessons} lesson(s)">harness${s.overlay_version?' v'+s.overlay_version:''} · ${s.lessons} lesson${s.lessons===1?'':'s'}</span>`};

const HV_DEC={adopt:'adopted a candidate',merge:'merged candidates',keep_base:'kept the base prompt'};
const HV_VERDICT={'no observed effect':'no effect'};

/* ---------------------------------------------------------------- cards */
function hvCard(s){const le=s.last_evolve;
  return `<button class="hv-card" type="button" data-hvc="${esc(s.step)}">
   <div class="hv-top">${icon(s.icon||'chart','lg')}<b>${esc(s.name)}</b>
    <span class="hv-ver ${s.overlay_version?'':'none'}">${s.overlay_version?'overlay v'+s.overlay_version:'no overlay'}</span></div>
   <p class="hv-short">${esc(s.short)}</p>
   <div class="hv-meta"><span>protocol <b>v${esc(s.protocol_version)}</b></span>
    <span><b>${s.lessons}</b> lesson${s.lessons===1?'':'s'}</span>
    <span>last evolve <b>${le?esc(HV_DEC[le.decision]||le.decision||'—'):'never'}</b></span></div>
   ${le&&le.reason?`<p class="hv-reason">${esc(String(le.reason).slice(0,180))}</p>`:''}
  </button>`}

async function hvPage(step){
  clearTimeout(HV.poll);
  await hvIndex();
  if(step){return hvDetail(step)}
  const st=HV.index||[];
  $('#app').innerHTML=`<div class="wrap">
   <div class="shead"><a class="back" href="#/">← All studies</a>
    <p class="eyebrow" style="margin-top:18px">SynthTwin · self-improving harness</p>
    <h2>Harness</h2>
    <p class="lede" style="max-width:72ch">The model stays frozen; what improves is the harness around each step. After you confirm a step, a reflector writes at most one lesson from what happened. An <b>evolve</b> run drafts two overlay edits — one about how the agent works, one about what a practitioner knows — replays the step's turn on recorded studies under each, and adopts one only if it behaves better. Everything is versioned; roll back anytime.</p></div>
   <section style="padding-top:4px"><div class="hv-grid">${st.map(hvCard).join('')}</div></section></div>`;
  document.querySelectorAll('[data-hvc]').forEach(b=>b.onclick=()=>{location.hash='#/harness/'+b.dataset.hvc});
}

/* ---------------------------------------------------------------- detail */
async function hvDetail(step){
  let d;try{d=await api('/api/harness/'+encodeURIComponent(step))}
  catch(e){$('#app').innerHTML=`<div class="wrap shead"><a class="back" href="#/harness">← Harness</a><h2>Not found</h2></div>`;return}
  HV.d=d;
  const lessons=d.experience.filter(r=>r.kind==='lesson');
  const changes=d.experience.filter(r=>r.kind==='change');
  const ev=(d.ledger||[]).slice().reverse().find(r=>r.kind==='evolve');
  const vers=Object.keys(d.overlays||{}).map(Number).sort((a,b)=>a-b);
  const cur=d.overlay_version;
  if(HV.diff.a===null){HV.diff.a=Math.max(0,vers.filter(v=>v<cur).pop()??0);HV.diff.b=cur}
  const roll=vers.filter(v=>v!==cur&&v>0);
  $('#app').innerHTML=`<div class="wrap">
   <div class="shead"><a class="back" href="#/harness">← Harness</a>
    <p class="eyebrow" style="margin-top:18px">Harness · ${esc(d.name)}</p>
    <h2>${esc(d.name)}</h2>
    <div class="hv-head">
     <span class="pill">protocol v${esc(d.protocol_version)}</span>
     <span class="pill ${cur?'upill':''}">${cur?'overlay v'+cur:'no overlay'}</span>
     <span class="pill">${lessons.length} lesson${lessons.length===1?'':'s'}</span>
     ${ev?`<span class="pill">last evolve ${new Date((ev.at||0)*1000).toLocaleString()} · ${esc(HV_DEC[ev.composer?.decision]||ev.composer?.decision||'')}</span>`:'<span class="pill">never evolved</span>'}
    </div>
    <div class="hv-acts">
     <button class="btn cu small" type="button" id="hvev">${icon('play')} Evolve</button>
     ${roll.length?`<select id="hvrb">${roll.map(v=>`<option value="${v}">v${v}</option>`).join('')}</select>
      <button class="btn ghost small" type="button" id="hvgo">Roll back</button>`:''}
    </div>
    <p class="hv-job" id="hvjob"></p>
   </div>

   <section class="hv-sec"><h3>${icon('doc')} Overlay</h3>
    <p class="help">Appended to this step's system prompt as "## Harness for this step" when the step runs. ${d.overlay?`Current: v${cur}.`:'No overlay adopted yet — the prompt is byte-identical to the protocol.'}</p>
    ${d.overlay?`<div class="hv-pre">${esc(d.overlay)}</div>
     <div class="hv-difftool">diff
      <select id="hvda">${vers.map(v=>`<option value="${v}" ${v===HV.diff.a?'selected':''}>${v?'v'+v:'base (none)'}</option>`).join('')}</select> →
      <select id="hvdb">${vers.map(v=>`<option value="${v}" ${v===HV.diff.b?'selected':''}>${v?'v'+v:'base (none)'}</option>`).join('')}</select>
      <span class="help" style="margin:0">red = removed, green = added</span></div>
     <div class="hv-diff" id="hvdiff"></div>`:''}
   </section>

   ${ev?`<section class="hv-sec"><h3>${icon('chart')} Last probe contrast</h3>
    <p class="help">The step's agent turn, replayed on ${ev.studies?.length||0} recorded stud${ev.studies?.length===1?'y':'ies'} (${(ev.studies||[]).map(id=>`<a href="#/s/${esc(id)}/${esc(d.step)}">${esc(id)}</a>`).join(', ')}) under the base prompt and each candidate overlay.</p>
    ${(ev.probes||[]).map(p=>hvProbe(p)).join('')}
    <div class="hv-comp"><b>${esc(HV_DEC[ev.composer?.decision]||ev.composer?.decision||'')}</b>${ev.composer?.choice?` <span class="pill">${esc(ev.composer.choice)}</span>`:''}
     ${hvChecks(ev.composer?.checks||{})}<p class="why">${esc(ev.composer?.reason||'')}</p></div>
    <details class="more"><summary>Candidates as drafted</summary><div class="inner">
     ${['inv','dom'].map(k=>{const c=ev.candidates?.[k]||{};return `<p><b>${k.toUpperCase()}</b> — ${c.action==='EDIT'?'edit':'KEEP_BASE'}${c.evidence?` · traced to: ${esc(c.evidence)}`:''}</p>
      ${c.overlay?`<div class="hv-pre">${esc(c.overlay)}</div>`:''}<p class="help" style="margin:4px 0 12px">${esc(c.moment||'')}</p>`}).join('')}
    </div></details></section>`:''}

   <section class="hv-sec"><h3>${icon('books')} Lessons</h3>
    <p class="help">Written by the reflector after this step is confirmed in real studies; at most one per study, evidence always linked. Injected (up to 5, by cue match) with the overlay.</p>
    ${lessons.length?lessons.slice().reverse().map(hvLesson).join(''):'<p class="empty" style="color:var(--ink3);font-size:14px">No lessons yet.</p>'}
   </section>

   <section class="hv-sec"><h3>${icon('checklist')} History</h3>
    <ol class="dec" style="margin-top:8px">${d.history.map(h=>`<li><span class="q">overlay v${h.version}${h.version===cur?' · current':''}</span>
     <span class="a">${new Date((h.at||0)*1000).toLocaleString()}</span><span class="w">${esc(h.note||'')}</span></li>`).join('')
     ||'<li><span class="q">no overlay versions</span><span class="a">—</span></li>'}
     ${changes.map(c=>`<li><span class="q">change ${esc(c.id)}</span><span class="a">${esc(c.action||'')}</span><span class="w">${esc(c.reason||'')}</span></li>`).join('')}</ol>
    <details class="more"><summary>Ledger (last ${d.ledger.length} runs)</summary><div class="inner">
     <div class="tbl"><table><thead><tr><th>at</th><th>kind</th><th>study</th><th>what</th></tr></thead><tbody>
      ${d.ledger.slice().reverse().map(r=>`<tr><td>${new Date((r.at||0)*1000).toLocaleTimeString()}</td><td>${esc(r.kind)}</td>
       <td>${r.study?`<a href="#/s/${esc(r.study)}/${esc(d.step)}">${esc(r.study)}</a>`:'—'}</td>
       <td>${esc(r.kind==='evolve'?(HV_DEC[r.composer?.decision]||''):(r.lesson?`lesson ${r.lesson}`:(r.rows||[]).map(x=>`${x.component}: ${x.verdict}`).join('; ')||'nothing observed'))}</td></tr>`).join('')}
     </tbody></table></div></div></details>
   </section></div>`;
  hvDiffRender();
  $('#hvev').onclick=()=>hvEvolve(d.step);
  const go=$('#hvgo');go&&(go.onclick=async()=>{go.disabled=true;
    try{await post(`/api/harness/${d.step}/rollback`,{version:+$('#hvrb').value});hvDetail(d.step)}catch(e){$('#hvjob').textContent=e.message;go.disabled=false}});
  $('#hvda').onchange=e=>{HV.diff.a=+e.target.value;hvDiffRender()};
  $('#hvdb').onchange=e=>{HV.diff.b=+e.target.value;hvDiffRender()};
  const job=await api(`/api/harness/${d.step}/evolve`).catch(()=>null);
  if(job&&job.job)hvJobLine(job.job);
}

function hvLesson(l){const v=l.verdict||'confounded';
  return `<div class="hv-lesson">
   <div class="hv-lrow"><span class="hv-v ${esc(v)}">${esc(HV_VERDICT[v]||v)}</span>
    ${l.confidence?`<span class="pill">confidence: ${esc(l.confidence)}</span>`:''}
    <span class="meta">${esc(l.id)} · ${esc(l.at||'')}</span></div>
   <span class="cue">${esc(l.cue||'')}</span>
   <span class="les">${esc(l.lesson||'')}</span>
   <span class="ev">${esc(l.evidence||'')}${l.study?` · <a href="#/s/${esc(l.study)}/${esc(l.step||'')}">${esc(l.study)}</a>`:''}</span>
  </div>`}

function hvProbe(p){const A=p.arms||{};
  return `<div class="hv-probe"><div class="hv-study">${esc(p.study)}</div>
   <div class="hv-arms">${Object.entries(A).map(([arm,o])=>`<div class="hv-arm">
    <span class="who"><b>${arm==='base'?'BASE':arm.toUpperCase()}</b>${o.delivered?'':'<span class="hv-v fail">no delivery</span>'}${o.ready?'<span class="hv-v ok">ready</span>':''}</span>
    <p>${esc((o.reply||'').slice(0,400)||'(no reply)')}</p></div>`).join('')}</div></div>`}

function hvChecks(c){return `<div class="hv-lrow" style="margin-top:8px">${Object.entries(c).map(([k,v])=>
  `<span class="hv-v ${esc(v)}" title="${esc(k)}: ${esc(v)}">${esc(k)} · ${esc(v)}</span>`).join('')}</div>`}

/* a simple line diff (LCS): enough for overlays, no library */
function hvDiffLines(a,b){const A=(a||'').split('\n'),B=(b||'').split('\n');
  const n=A.length,m=B.length,dp=Array.from({length:n+1},()=>new Uint32Array(m+1));
  for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)
    dp[i][j]=A[i]===B[j]?dp[i+1][j+1]+1:Math.max(dp[i+1][j],dp[i][j+1]);
  const out=[];let i=0,j=0;
  while(i<n&&j<m){if(A[i]===B[j]){out.push([' ',A[i]]);i++;j++}
    else if(dp[i+1][j]>=dp[i][j+1]){out.push(['-',A[i]]);i++}
    else{out.push(['+',B[j]]);j++}}
  while(i<n)out.push(['-',A[i++]]);while(j<m)out.push(['+',B[j++]]);
  return out}
function hvDiffRender(){const el=$('#hvdiff');if(!el||!HV.d)return;const O=HV.d.overlays||{};
  const a=String(O[String(HV.diff.a)]??''),b=String(O[String(HV.diff.b)]??'');
  el.innerHTML=hvDiffLines(a,b).map(([m,t])=>
    `<div class="${m==='-'?'d':m==='+'?'a':'ctx'}">${m===' '?'' :m==='-'?'−':'+'} ${esc(t)||' '}</div>`).join('')||'<div class="ctx">(identical)</div>'}

/* ---------------------------------------------------------------- evolve job */
function hvJobLine(j){const el=$('#hvjob');if(!el||!j)return;
  el.innerHTML=j.status==='running'?`<span class="spin"></span> evolving ${esc(j.step)} (probing recorded studies)…`
   :j.status==='failed'?`<span class="err">${esc(j.error||'failed')}</span>`
   :`done · ${esc(HV_DEC[j.result?.composer?.decision]||j.result?.composer?.decision||'')} — ${esc((j.result?.composer?.reason||'').slice(0,200))}`;
  clearTimeout(HV.poll);
  if(j.status==='running')HV.poll=setTimeout(async()=>{const r=await api(`/api/harness/${j.step}/evolve?id=${encodeURIComponent(j.id)}`).catch(()=>null);
    if(r&&r.job){hvJobLine(r.job);if(r.job.status!=='running')hvDetail(j.step)}},2500)}

async function hvEvolve(step){const b=$('#hvev');b.disabled=true;b.innerHTML='<span class="spin"></span> Evolving…';
  try{const j=await post(`/api/harness/${step}/evolve`,{});
    hvJobLine(j);clearTimeout(HV.poll);
    HV.poll=setTimeout(async()=>{const r=await api(`/api/harness/${step}/evolve?id=${encodeURIComponent(j.id)}`).catch(()=>null);
      if(r&&r.job){hvJobLine(r.job);if(r.job.status!=='running')hvDetail(step)}},2500)}
  catch(e){$('#hvjob').textContent=e.message;b.disabled=false;b.innerHTML='Evolve'}}

HV.page=hvPage;
hvIndex();
