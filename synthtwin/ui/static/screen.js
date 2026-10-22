/* SynthTwin auto-search ("screener"): name a material type + application, scan
   LeMat-Synth for the best reported results, steer the leaderboard, queue studies.
   Uses $, esc, api, post from index.html. Loaded after agent.js.
   Ranks are recomputed client-side from the components the scan returns, so the
   weight sliders / drops / budget never rescans; "Rescan" sends a new POST. */
const SC={meta:null,id:null,res:null,queued:{},fams:[],w:{record:.4,data:.25,sim:.25,recent:.1},
  budget:3,explore:.4,drop:{},checks:{},texts:{},open:{},poll:null,past:[]};

const COMP=["record","data","sim","recent"];
const CWORD={record:"closeness to the state of the art",data:"enough recipes with conditions to calibrate",
  sim:"our simulation catalogue covers the route",recent:"reports from the last 3 years"};
const FLAB={all:"syntheses",rows:"syntheses",material:"material match",application:"application",
  metric:"report the metric",reports:"report the metric",families:"families"};
const sfmt=v=>v==null||isNaN(v)||v===""?"—":Math.abs(v)>=1e5||Math.abs(v)<0.01&&+v!==0?(+v).toExponential(2):(+v).toPrecision(3).replace(/(\.\d*?)0+$/,"$1").replace(/\.$/,"");
const fint=n=>(+n||0).toLocaleString("en-US");
const pyround=x=>Math.floor(+x+0.5);   // half-up, same as scan._round_half_up
const arr=v=>Array.isArray(v)?v:v==null||v===""?[]:String(v).split(",").map(s=>s.trim()).filter(Boolean);
const escRE=s=>s.replace(/[.*+?^${}()|[\]\\]/g,"\\$&");

async function screenMeta(){if(!SC.meta)SC.meta=await api("/api/screen");return SC.meta}

/* ---------------------------------------------------------------- contract normalisation
   The backend worker owns scan.py; these flatten whatever nesting it settles on
   (components as numbers or {value,why}, best.paper flat or nested) into one shape. */
function normFamily(f,i){
  const c={},why={};const src=f.components||f;
  for(const k of COMP){const v=src[k];
    if(v&&typeof v==="object"){c[k]=+v.value||0;why[k]=v.why||v.reason||""}
    else{c[k]=+v||0;why[k]=(f.reasons||f.why||{})[k]||""}}
  const b=f.best||{};const p=b.paper||b;
  return {family:f.family||f.name||"",names:f.names||f.raw_names||[],
    best:{value:b.value,unit:b.unit||f.unit||"",year:p.year,title:p.title||p.paper_title||"",
      url:p.url||(p.doi?"https://doi.org/"+p.doi:""),doi:p.doi||"",snippet:p.snippet||b.snippet||""},
    median:f.median,n_reports:+f.n_reports||0,n_papers:+f.n_papers||0,methods:f.methods||[],
    richness:f.richness,years:Array.isArray(f.years)?f.years:[],
    c,why,score:+f.score||0,label:f.label||"",suggest:!!f.suggest,
    study_text:f.study_text||"",why_beatable:f.why_beatable||"",i};
}
function normScreen(r){
  const q=r.query||{};let mt=r.metric||null;
  if(typeof mt==="string")mt=(SC.meta?.metrics||[]).find(m=>m.key===mt)||{key:mt,name:mt,unit:"",better:"max"};
  return {id:r.id||"",created:+r.created||Date.now()/1000,
    query:{material:q.material||"",application:q.application||"",metric:q.metric??null,
      include:arr(q.include),exclude:arr(q.exclude),budget:+q.budget||3,explore:q.explore??.4,deep:!!q.deep},
    metric:mt,n_rows:+r.n_rows||+SC.meta?.n_rows||0,
    funnel:(r.funnel||[]).map(s=>({label:String(s.label??s.name??"").replace(/_/g," "),n:+s.n||0})),
    global_best:r.global_best||null,weights:{record:.4,data:.25,sim:.25,recent:.1,...(r.weights||{})},
    families:(r.families||[]).map(normFamily)};
}
function normQueued(r){   // ids in "queued" ({family: study id}), live phase/status in "queued_studies"
  const one=v=>typeof v==="string"?{id:v}:{id:v.id||v.study_id||v.sid,phase:v.phase,status:v.status,busy:!!v.busy,title:v.title};
  const q={};for(const[fam,v]of Object.entries(r.queued_studies||{}))q[fam]=one(v);
  for(const[fam,v]of Object.entries(r.queued||{}))if(!q[fam])q[fam]=one(v);
  return q}
function normPast(r){const L=Array.isArray(r)?r:r.screens||r.list||[];
  return L.map(s=>({id:s.id,created:+s.created||0,query:s.query||{},
    n_families:+(s.n_families??s.families??0)||0,
    n_queued:+(s.n_queued??(s.queued?Object.keys(s.queued).length:0))||0}))}
function normExample(e){
  if(e&&typeof e==="object")return {material:e.material||"",application:e.application||"",label:`${e.material||""} · ${e.application||""}`};
  const s=String(e||"");const m=s.split(/\s*[·/—→]\s*|\s+for\s+/i);
  return m.length>=2?{material:m[0].trim(),application:m.slice(1).join(" ").trim(),label:s}:{material:s,application:"",label:s};
}

/* ---------------------------------------------------------------- client-side metric pick
   Same rule as metrics.pick: keyword match on the application, longest keyword wins. */
function pickMetric(app){
  if(!SC.meta)return null;const t=String(app||"").toLowerCase();let best=null,bl=0;
  for(const m of SC.meta.metrics||[])for(const k of m.apps||[]){
    const kw=String(k).toLowerCase();
    if(kw&&kw.length>bl&&new RegExp(`(^|[^a-z0-9])${escRE(kw)}([^a-z0-9]|$)`).test(t)){best=m;bl=kw.length}}
  return best;
}

/* ---------------------------------------------------------------- re-rank (same rule as scan.py) */
function rerank(){
  const w=SC.w;const fams=SC.fams.filter(f=>!SC.drop[f.family]);
  for(const f of fams)f.score=w.record*f.c.record+w.data*f.c.data+w.sim*f.c.sim+w.recent*f.c.recent;
  fams.sort((a,b)=>b.score-a.score||b.n_reports-a.n_reports||(a.family<b.family?-1:a.family>b.family?1:0));  // scan._sort tiebreak
  const nEx=Math.min(fams.length,Math.max(0,pyround(SC.budget*(1-SC.explore))));
  fams.forEach(f=>{f.label="";f.suggest=false});
  fams.slice(0,nEx).forEach(f=>{f.label="exploit"});
  let used=nEx;
  for(const f of fams.slice(nEx)){if(used>=SC.budget)break;
    if(f.n_reports<=2||(f.c.record>=.8&&f.c.data<.5)){f.label="explore";used++}}
  fams.forEach(f=>{if(f.label)f.suggest=true});
  return fams;
}

/* ---------------------------------------------------------------- pages */
async function scPage(id){
  clearTimeout(SC.poll);SC.id=id||null;
  try{SC.past=normPast(await api("/api/screens"))}catch(e){SC.past=[]}
  try{await screenMeta()}catch(e){SC.meta=null}
  if(!id)return renderIntro();
  if(!SC.res||SC.res.id!==id){
    try{applyScreen(await api("/api/screen/"+encodeURIComponent(id)))}
    catch(e){$("#app").innerHTML=`<div class="wrap"><div class="shead"><a class="back" href="#/screen">← Auto-search</a>
      <h2>Screen not found</h2><p class="help">${esc(e.message)}</p></div>${pastHtml()}</div>`;return}}
  renderResult();pollScreen();
}
function applyScreen(r){
  SC.res=normScreen(r);SC.queued=normQueued(r);SC.fams=SC.res.families;
  SC.w={...SC.res.weights};SC.budget=SC.res.query.budget||3;SC.explore=SC.res.query.explore??.4;
  SC.drop={};SC.checks={};SC.texts={};SC.open={};
}

function renderIntro(){
  const m=SC.meta;const on=m&&m.enabled;
  $("#app").innerHTML=`<div class="wrap">
   <div class="sc-hero"><p class="eyebrow">SynthTwin · auto-search</p>
    <h1>Name the material.<br>Find what to <em>beat</em>.</h1>
    <p class="lede">Manual is the default: describe one problem and the agent takes it from there. Auto-search is the other way in: name a material type and an application; it scans LeMat-Synth for the best reported results and queues studies to beat them.</p>
    ${on?`<p class="help">${fint(m.n_rows)} extracted syntheses from arXiv, ChemRxiv and OMG24 papers, indexed for figures of merit.</p>`
       :`<div class="callout warn" style="margin-top:16px">Auto-search is off on this server${m?"":" (no /api/screen)"}: start it with <code>--screen-index</code>.</div>`}
   </div>
   ${on?`<section><h3>Scan LeMat-Synth</h3>${formHtml(null,"Scan LeMat-Synth")}</section>`:""}
   ${pastHtml()}</div>`;
  if(on)bindForm();
}

/* ---------------------------------------------------------------- the scan form (also reused, prefilled, for Rescan) */
function formHtml(q,label){
  q=q||{material:"",application:"",metric:null,include:[],exclude:[],budget:3,explore:.4,deep:false};
  const cats=(SC.meta?.categories||[]).map(c=>Array.isArray(c)?{name:c[0],n:c[1]}:c).slice(0,15);
  const exs=(SC.meta?.examples||[]).map(normExample).filter(e=>e.material);
  const ex=Math.round((q.explore??.4)*100);
  return `<div class="sc-form" id="scform">
   <div class="sc-grid">
    <div class="field"><label class="lbl" for="sc-mat">Material type</label>
     <input id="sc-mat" value="${esc(q.material)}" placeholder="e.g. perovskite, MOF, cathode">
     <div class="mchips">${cats.map(c=>`<button type="button" class="chip" data-matc="${esc(c.name||c.category||"")}">${esc(c.name||c.category||"")}${c.n!=null?` · ${fint(c.n)}`:""}</button>`).join("")}</div></div>
    <div class="field"><label class="lbl" for="sc-app">Application</label>
     <input id="sc-app" value="${esc(q.application)}" placeholder="e.g. solar cell, CO2 capture, LED"></div>
    <div class="field"><label class="lbl" for="sc-metric">Figure of merit</label>
     <select id="sc-metric"><option value="auto">auto</option>${(SC.meta?.metrics||[]).map(m=>`<option value="${esc(m.key)}" ${q.metric===m.key?"selected":""}>${esc(m.name)} (${esc(m.unit)})</option>`).join("")}</select>
     <p class="help" id="sc-mh"></p></div>
    <div class="field"><label class="lbl" for="sc-inc">Include words <span class="opt">(optional)</span></label>
     <input id="sc-inc" value="${esc((q.include||[]).join(", "))}" placeholder="comma-separated; all must appear"></div>
    <div class="field"><label class="lbl" for="sc-exc">Exclude words <span class="opt">(optional)</span></label>
     <input id="sc-exc" value="${esc((q.exclude||[]).join(", "))}" placeholder="comma-separated; none may appear"></div>
    <div class="field"><label class="lbl" for="sc-budget">Budget <span class="opt">(studies to queue)</span></label>
     <input id="sc-budget" type="number" min="1" max="10" value="${q.budget||3}"></div>
    <div class="field"><label class="lbl" for="sc-explore">Explore share</label>
     <input id="sc-explore" type="range" min="0" max="100" step="5" value="${ex}">
     <p class="help" id="sc-exv">${ex}% · the rest goes to the safest bets</p></div>
    <div class="field"><span class="lbl">Deep pass <span class="opt">(optional)</span></span>
     <label class="sc-tog"><input type="checkbox" id="sc-deep" ${q.deep?"checked":""}> Check the abstracts with the LLM</label></div>
   </div>
   ${exs.length?`<div class="mchips">${exs.map(e=>`<button type="button" class="chip" data-exq="${esc(JSON.stringify(e))}">e.g. ${esc(e.label)}</button>`).join("")}</div>`:""}
   <p class="err" id="sc-ferr"></p>
   <div><button class="btn cu big" type="button" id="sc-go" data-lab="${esc(label)}">${esc(label)}</button></div></div>`;
}
function bindForm(){
  const q=id=>$(id);
  document.querySelectorAll("[data-matc]").forEach(c=>c.onclick=()=>{q("#sc-mat").value=c.dataset.matc;q("#sc-mat").focus()});
  document.querySelectorAll("[data-exq]").forEach(c=>c.onclick=()=>{
    const e=JSON.parse(c.dataset.exq);q("#sc-mat").value=e.material;if(e.application)q("#sc-app").value=e.application;metricHint()});
  q("#sc-app").oninput=metricHint;q("#sc-metric").onchange=metricHint;metricHint();
  q("#sc-explore").oninput=e=>{q("#sc-exv").textContent=`${e.target.value}% · the rest goes to the safest bets`;
    SC.explore=+e.target.value/100;const s=$("#sc-w-explore");if(s){s.value=e.target.value;const v=$('.sc-steer .val[data-v="explore"]');if(v)v.textContent=e.target.value+"%"}};
  q("#sc-budget").onchange=e=>{SC.budget=Math.max(1,Math.min(10,+e.target.value||3));const s=$("#sc-w-budget");if(s){s.value=SC.budget;const v=$('.sc-steer .val[data-v="budget"]');if(v)v.textContent=SC.budget}};
  q("#sc-go").onclick=doScan;
}
function metricHint(){
  const sel=$("#sc-metric"),h=$("#sc-mh");if(!sel||!h||!SC.meta)return;
  const app=$("#sc-app").value.trim();
  if(sel.value!=="auto"){const m=(SC.meta.metrics||[]).find(x=>x.key===sel.value);
    h.textContent=m?`${m.name} (${m.unit}) — ${m.better==="min"?"lower":"higher"} is better`:"";return}
  if(!app){h.textContent="auto: derived from the application";return}
  const m=pickMetric(app);
  h.textContent=m?`auto → ${m.name} (${m.unit})`:"auto → no metric matches this application yet; pick one above";
}
function readForm(){
  const g=id=>{const e=$(id);return e?e.value.trim():""};
  return {material:g("#sc-mat"),application:g("#sc-app"),
    metric:$("#sc-metric")&&$("#sc-metric").value!=="auto"?$("#sc-metric").value:null,
    include:g("#sc-inc").split(",").map(s=>s.trim()).filter(Boolean),
    exclude:g("#sc-exc").split(",").map(s=>s.trim()).filter(Boolean),
    budget:Math.max(1,Math.min(10,+g("#sc-budget")||3)),
    explore:(+($("#sc-explore")?.value??40)||40)/100,deep:!!($("#sc-deep")?.checked)};
}
async function doScan(){
  const q=readForm();const er=$("#sc-ferr")||$("#scerr");const b=$("#sc-go");
  if(!q.material&&er){er.textContent="Name a material type (e.g. perovskite).";return}
  if(!q.application&&er){er.textContent="Name an application (e.g. solar cell).";return}
  b.disabled=true;b.innerHTML='<span class="spin"></span>Scanning';
  try{
    const r=await post("/api/screen",q);applyScreen(r);
    if(location.hash==="#/screen/"+SC.res.id){renderResult();pollScreen()}
    else location.hash="#/screen/"+SC.res.id;
  }catch(e){if(er)er.textContent=e.message;b.disabled=false;b.textContent=b.dataset.lab||"Scan LeMat-Synth"}
}

/* ---------------------------------------------------------------- result page */
function renderResult(){
  const r=SC.res,q=r.query,mt=r.metric;
  $("#app").innerHTML=`<div class="wrap">
   <div class="shead"><a class="back" href="#/screen">← Auto-search</a>
    <p class="eyebrow" style="margin-top:18px">Auto-search · ${fint(r.n_rows)} syntheses scanned${q.deep?" · abstracts checked by the LLM":""}</p>
    <h2>${esc(q.material)} <span class="muted">·</span> ${esc(q.application)}</h2>
    <p class="help">${mt?`${esc(mt.name)} (${esc(mt.unit)}), ${mt.better==="min"?"lower":"higher"} is better · ${new Date(r.created*1000).toLocaleString()}`
      :`no figure of merit matched · ${new Date(r.created*1000).toLocaleString()}`}</p></div>
   <section style="padding-top:10px">
    ${funnelHtml(r)}${bestHtml(r)}
    <details class="more" id="sc-editq"><summary>Edit the query & rescan</summary><div class="inner">${formHtml(q,"Rescan LeMat-Synth")}</div></details>
    <div class="sc-steer">${COMP.map(k=>`<div class="sc-sw"><label for="sc-w-${k}">${k} — ${CWORD[k]}</label>
      <input type="range" id="sc-w-${k}" data-k="${k}" min="0" max="100" step="5" value="${Math.round((SC.w[k]||0)*100)}">
      <b class="val num" data-v="${k}">${Math.round((SC.w[k]||0)*100)}%</b></div>`).join("")}
     <div class="sc-sw"><label for="sc-w-budget">budget (studies)</label><input type="range" id="sc-w-budget" data-k="budget" min="1" max="10" step="1" value="${SC.budget}"><b class="val num" data-v="budget">${SC.budget}</b></div>
     <div class="sc-sw"><label for="sc-w-explore">explore share</label><input type="range" id="sc-w-explore" data-k="explore" min="0" max="100" step="5" value="${Math.round(SC.explore*100)}"><b class="val num" data-v="explore">${Math.round(SC.explore*100)}%</b></div>
    </div>
    <div class="sc-toolrow"><div class="legend sc-legend" id="sc-legend"></div>
     <div class="sc-acts"><span class="meta" id="sc-dropped"></span><button class="btn cu" type="button" id="sc-queue">Queue 0 studies</button></div></div>
    <div class="sc-board"><table>
     <thead><tr><th></th><th>#</th><th>family</th><th>best reported</th><th>rep/pap</th><th>score</th><th>label</th><th>study</th><th>why</th><th></th></tr></thead>
     <tbody id="sc-rows"></tbody></table></div>
    <p class="err" id="scerr"></p>
   </section>
   ${pastHtml()}</div>`;
  bindForm();bindResult();renderBoard();legend();
}
function funnelHtml(r){
  let steps=r.funnel;
  if(!steps.length)steps=[{label:"syntheses",n:r.n_rows},{label:"families",n:(r.families||[]).length}];
  return `<div class="sc-funnel">${steps.map((s,i)=>`${i?'<span class="fa">→</span>':''}<div class="fs"><b>${fint(s.n)}</b><span>${esc(FLAB[s.label.toLowerCase()]||s.label.charAt(0).toUpperCase()+s.label.slice(1))}</span></div>`).join("")}</div>`;
}
function bestHtml(r){
  const b=r.global_best;if(!b||b.value==null)return "";
  const p=b.paper||b;const url=p.url||(p.doi?"https://doi.org/"+p.doi:"");
  return `<div class="sc-best"><div><span class="lbls">best reported</span><b class="num">${sfmt(b.value)} ${esc(b.unit||"")}</b></div>
   <div><span class="lbls">material</span>${esc(b.material||b.family||"—")}</div>
   ${url?`<div><span class="lbls">paper</span><a href="${esc(url)}" target="_blank" rel="noopener">${esc(p.title||p.doi||"paper")} ↗</a>${p.year?` <span class="meta">${esc(String(p.year))}</span>`:""}</div>`:""}</div>`;
}

/* ---------------------------------------------------------------- leaderboard */
function barHtml(f){
  return `<span class="sc-bar" role="img" aria-label="score ${f.score.toFixed(2)} of 1">${COMP.map(k=>{
    const v=f.c[k]*SC.w[k];
    return `<i style="width:${(v*100).toFixed(2)}%;${v>0.002?"min-width:2px;":""}background:var(--sc-${k})" title="${k} ${f.c[k].toFixed(2)} × w ${SC.w[k].toFixed(2)}${f.why[k]?" — "+esc(f.why[k]):""}"></i>`}).join("")}</span>`;
}
function whyText(f){
  if(f.why_beatable)return f.why_beatable;
  return COMP.map(k=>f.why[k]).filter(Boolean).join(" · ");
}
function studPill(q){
  const cls=q.busy?"running":q.status==="complete"?"complete":q.status==="awaiting_user"?"awaiting_user":"";
  const txt=q.busy?"working":q.status==="complete"?"complete":q.status==="awaiting_user"?"needs you":(q.phase||q.status||"queued");
  return `<a class="status ${cls}" href="#/s/${esc(q.id)}" title="open the study">${esc(txt)}</a>`;
}
function rowsHtml(fams){
  return fams.map((f,i)=>{
    const q=SC.queued[f.family];
    if(!(f.family in SC.checks))SC.checks[f.family]=!!f.suggest&&!q;
    const ck=SC.checks[f.family],open=!!SC.open[f.family];
    return `<tr class="sc-r ${open?"open":""}" data-f="${esc(f.family)}">
     <td>${q?"":`<input type="checkbox" data-ck="${esc(f.family)}" ${ck?"checked":""} aria-label="queue ${esc(f.family)}">`}</td>
     <td class="num sc-rk">${i+1}</td>
     <td class="sc-fm"><button class="sc-xp" data-xp="${esc(f.family)}" aria-label="expand ${esc(f.family)}">${open?"▾":"▸"}</button><b title="${esc(f.names.join(" · "))}">${esc(f.family)}</b></td>
     <td class="sc-bv"><b class="num">${sfmt(f.best.value)}${f.best.unit?" "+esc(f.best.unit):""}</b>${f.best.url?` <a href="${esc(f.best.url)}" target="_blank" rel="noopener">paper↗</a>`:""}${f.best.year?` <span class="meta">${esc(String(f.best.year))}</span>`:""}</td>
     <td class="num">${f.n_reports} / ${f.n_papers}</td>
     <td class="sc-sc">${barHtml(f)} <b class="num">${f.score.toFixed(2)}</b></td>
     <td>${f.label?`<span class="pill ${f.label==="exploit"?"pe":"px"}">${f.label}</span>`:""}</td>
     <td>${q?studPill(q):""}</td>
     <td class="sc-wh">${esc(whyText(f))}</td>
     <td>${q?"":`<button class="sc-dr" data-dr="${esc(f.family)}" title="drop ${esc(f.family)} from the ranking (keeps it out of the labels, no rescan)">✕</button>`}</td>
    </tr>${detailHtml(f)}`;
  }).join("");
}
function detailHtml(f){
  const txt=SC.texts[f.family]!=null?SC.texts[f.family]:f.study_text;
  return `<tr class="sc-d" data-d="${esc(f.family)}" ${SC.open[f.family]?"":"hidden"}><td colspan="10"><div class="sc-dg">
    <div><span class="lbls">study text — editable; queued as the agent's problem</span>
     <textarea data-tx="${esc(f.family)}" placeholder="study text">${esc(txt)}</textarea></div>
    <div>${f.best.snippet?`<span class="lbls">best reported · snippet</span><blockquote class="sc-sn">${esc(f.best.snippet)}</blockquote>`:""}
     <span class="lbls">score components</span>
     <table class="sc-ct"><tbody>${COMP.map(k=>`<tr><td><i style="background:var(--sc-${k})"></i>${k}</td>
       <td class="num">${f.c[k].toFixed(2)}</td><td class="num">× ${SC.w[k].toFixed(2)}</td><td>${esc(f.why[k]||CWORD[k])}</td></tr>`).join("")}</tbody></table>
     <p class="meta">${esc(f.methods.join(", "))}${f.years.length?` · ${esc(String(f.years[0]))}–${esc(String(f.years[f.years.length-1]))}`:""}${f.median!=null?` · median ${sfmt(f.median)}${f.best.unit?" "+esc(f.best.unit):""}`:""}</p></div>
   </div></td></tr>`;
}
function renderBoard(){
  const tb=$("#sc-rows");if(!tb)return;
  const ae=document.activeElement;   // never yank focus out of a textarea mid-edit (poll refresh)
  if(ae&&ae.closest&&ae.closest("#sc-rows")&&ae.matches("textarea"))return;
  tb.innerHTML=rowsHtml(rerank());
  queueLabel();renderDropped();
}
function queueLabel(){
  const b=$("#sc-queue");if(!b)return;
  const n=rerank().filter(f=>SC.checks[f.family]&&!SC.queued[f.family]).length;
  b.textContent=`Queue ${n} ${n===1?"study":"studies"}`;b.disabled=!n;
}
function renderDropped(){
  const el=$("#sc-dropped");if(!el)return;const d=Object.keys(SC.drop);
  el.innerHTML=d.length?`dropped: ${d.map(f=>`<button type="button" class="chip" data-un="${esc(f)}" title="restore ${esc(f)}">${esc(f)} ↺</button>`).join(" ")}`:"";
}
function syncExclude(fam,add){   // drops also land in the query's exclude words, so a Rescan keeps them out
  const i=$("#sc-exc");if(!i)return;
  const ws=i.value.split(",").map(s=>s.trim()).filter(Boolean);
  const j=ws.indexOf(fam);
  if(add&&j<0)ws.push(fam);
  if(!add&&j>=0)ws.splice(j,1);
  i.value=ws.join(", ");
}
function legend(){
  const el=$("#sc-legend");if(!el)return;
  el.innerHTML=COMP.map(k=>`<span><i style="background:var(--sc-${k})"></i>${k} <b class="num">${Math.round((SC.w[k]||0)*100)}</b></span>`).join("")
    +`<span class="meta">score = Σ weight × component</span>`;
}
function toggleFam(f){
  SC.open[f]=!SC.open[f];
  const row=$(`#sc-rows tr.sc-r[data-f="${CSS.escape(f)}"]`),det=$(`#sc-rows tr.sc-d[data-d="${CSS.escape(f)}"]`);
  if(row&&det){det.hidden=!SC.open[f];row.classList.toggle("open",SC.open[f]);
    const xp=row.querySelector(".sc-xp");if(xp)xp.textContent=SC.open[f]?"▾":"▸"}
}
function bindResult(){
  document.querySelectorAll(".sc-steer input[type=range]").forEach(s=>s.oninput=()=>{
    const k=s.dataset.k;
    if(COMP.includes(k))SC.w[k]=+s.value/100;
    if(k==="budget")SC.budget=+s.value;
    if(k==="explore")SC.explore=+s.value/100;
    const v=$(`.sc-steer .val[data-v="${k}"]`);if(v)v.textContent=k==="budget"?s.value:s.value+"%";
    const fb=$("#sc-budget"),fe=$("#sc-explore");
    if(k==="budget"&&fb)fb.value=SC.budget;
    if(k==="explore"&&fe){fe.value=s.value;const ev=$("#sc-exv");if(ev)ev.textContent=`${s.value}% · the rest goes to the safest bets`}
    legend();renderBoard()});
  const tb=$("#sc-rows");
  tb.onclick=e=>{
    const xp=e.target.closest("[data-xp]");if(xp)return toggleFam(xp.dataset.xp);
    const dr=e.target.closest("[data-dr]");
    if(dr){delete SC.checks[dr.dataset.dr];SC.drop[dr.dataset.dr]=1;syncExclude(dr.dataset.dr,true);return renderBoard()}
    const tr=e.target.closest("tr.sc-r");
    if(tr&&!e.target.closest("a,input,button"))toggleFam(tr.dataset.f)};
  tb.onchange=e=>{const c=e.target.closest("[data-ck]");if(c){SC.checks[c.dataset.ck]=c.checked;queueLabel()}};
  tb.oninput=e=>{const t=e.target.closest("[data-tx]");if(t)SC.texts[t.dataset.tx]=t.value};
  $("#sc-dropped").onclick=e=>{const u=e.target.closest("[data-un]");
    if(u){delete SC.drop[u.dataset.un];syncExclude(u.dataset.un,false);renderBoard()}};
  $("#sc-queue").onclick=doQueue;
}
async function doQueue(){
  const fams=rerank().filter(f=>SC.checks[f.family]&&!SC.queued[f.family]).map(f=>f.family);
  if(!fams.length)return;
  const texts={};fams.forEach(fn=>{if(SC.texts[fn]!=null)texts[fn]=SC.texts[fn]});
  const b=$("#sc-queue");b.disabled=true;b.innerHTML='<span class="spin"></span>Queuing';
  try{
    const r=await post(`/api/screen/${encodeURIComponent(SC.id)}/queue`,{families:fams,texts});
    SC.res=normScreen(r);SC.queued=normQueued(r);SC.fams=SC.res.families;
    renderBoard();pollScreen();
  }catch(e){$("#scerr").textContent=e.message;b.disabled=false;queueLabel()}
}

/* ---------------------------------------------------------------- past screens + polling */
function pastHtml(){
  const L=SC.past;if(!L.length)return "";
  return `<section><h3>Past screens</h3><div class="sc-past">${L.map(s=>`<a class="sc-pc" href="#/screen/${esc(s.id)}">
    <b>${esc(s.query.material||s.id)}</b><span>for ${esc(s.query.application||"—")}</span>
    <span class="meta">${new Date(s.created*1000).toLocaleString()} · ${s.n_families} families${s.n_queued?` · ${s.n_queued} queued`:""}</span></a>`).join("")}</div></section>`;
}
function pollScreen(){
  clearTimeout(SC.poll);
  if(!SC.id||!Object.values(SC.queued).some(q=>q.busy))return;
  SC.poll=setTimeout(async()=>{
    if(!location.hash.startsWith("#/screen/"))return;
    try{const r=await api("/api/screen/"+encodeURIComponent(SC.id));
      SC.res=normScreen(r);SC.queued=normQueued(r);SC.fams=SC.res.families;renderBoard()}
    catch(e){}
    pollScreen();
  },5000);
}

SC.page=scPage;
