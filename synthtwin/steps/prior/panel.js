/* The prior step's panel: the related studies (benchmark cards, the mined
   library, the literature) with a mini chart per study. AG, wait, icon, fmt,
   esc and lineChart come from agent.js / common.js. */
/* ---- related studies */
const SRC_ICON={benchmark:'shield',web:'doc',library:'book'};
function srcPill(x){const i=icon(SRC_ICON[x.source]||'doc','lg2');
  return x.source==='benchmark'?`<span class="pill blind">${i}${x.blind?'benchmark · blind':'benchmark · revealed'}</span>`
  :x.source==='web'?`<span class="pill web">${i}literature · agent-read${x.confidence?' · '+esc(x.confidence):''}</span>`
  :`<span class="pill lib">${i}mined library</span>`}
function studyBox(x,q){const sw=x.swept||[];const key=sw[0]?.key;
  const pts=(x.points||[]).filter(p=>p.value!=null||key&&p.conditions&&p.conditions[key]!=null);
  const vis=pts.filter(p=>p.outcomes&&p.outcomes[q]!=null).map(p=>[+(p.value??p.conditions[key]),p.outcomes[q]]);
  const sealed=pts.filter(p=>p.state&&p.state.startsWith('sealed')).map(p=>+(p.value??p.conditions[key]));
  const mini=key&&vis.length===1&&sealed.length?blindStrip(key,q,vis[0],sealed):key&&vis.length>=2?lineChart({w:300,h:120,xlab:key,ylab:q,mini:true,
    series:[{pts:vis.map(v=>[v[0],v[1]]),color:'#d8894f',dots:true,line:vis.length>1&&sw.length===1}],marks:sealed}):'';
  return `<div class="abox"><div class="row">${srcPill(x)}<span class="pill">${esc(x.material)}</span>${x.method?`<span class="pill">${esc(x.method)}</span>`:''}${x.year?`<span class="pill">${esc(String(x.year).slice(0,4))}</span>`:''}</div>
   <h4>${x.url?`<a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(x.title||x.id)}</a>`:esc(x.title||x.id)}</h4>
   <div class="relbar" title="relevance ${x.relevance}"><i style="width:${Math.round(x.relevance*100)}%"></i></div>
   <p class="help" style="margin:0">${esc((x.why||[]).join(' · ')||'weakly related')}</p>
   ${sw.length?`<div><span class="lbl">swept</span>${sw.map(w=>`<div class="row"><span class="pill">${esc(w.key)}</span>${(w.values||[]).slice(0,10).map(v=>`<span class="pill p">${esc(typeof v==='number'?fmt(v):v)}</span>`).join('')}</div>`).join('')}</div>`:''}
   ${Object.keys(x.fixed||{}).length?`<div><span class="lbl">held fixed</span><div class="row">${Object.entries(x.fixed).slice(0,8).map(([k,v])=>`<span class="pill p">${esc(k)}=${esc(typeof v==='number'?fmt(v):v)}</span>`).join('')}</div></div>`:''}
   <div class="row"><span class="lbl" style="margin:0">measured</span>${(x.quantities||[]).map(z=>`<span class="pill">${esc(z)}</span>`).join('')||'<span class="help">no outcomes</span>'}</div>
   ${mini?`<div class="chart" style="padding:8px">${mini}${sealed.length&&vis.length>1?'<p class="cs">ticks on the axis: points sealed until the benchmark</p>':''}</div>`:''}
   ${x.takeaway?`<p>${esc(x.takeaway)}</p>`:''}<p class="help" style="margin:0">${esc(x.note||'')}</p></div>`}
/* a blind card reveals one anchor point: show the sweep as a strip, the anchor
   with its value and every sealed point as a "?" (no fake 2-D chart from one dot) */
function blindStrip(key,q,an,sealed){const W=300,H=74,l=14,r=14,y=34;const xs=sealed.concat([an[0]]);
  let x0=Math.min(...xs),x1=Math.max(...xs);if(x1===x0){x0-=1;x1+=1}const fx=v=>l+(v-x0)/(x1-x0)*(W-l-r);
  let g=`<line x1="${l}" x2="${W-r}" y1="${y}" y2="${y}" stroke="rgba(255,255,255,.18)" stroke-dasharray="3 4"/>`;
  const lab=[fx(an[0])];const room=x=>lab.every(u=>Math.abs(u-x)>22)&&(lab.push(x),true);
  sealed.slice().sort((a,b)=>a-b).forEach(v=>{g+=`<circle cx="${fx(v)}" cy="${y}" r="7" fill="var(--bg2)" stroke="#8b8983" stroke-dasharray="2 2"/><text x="${fx(v)}" y="${y+3.5}" text-anchor="middle" style="fill:#8b8983;font-weight:600">?</text>
    ${room(fx(v))?`<text x="${fx(v)}" y="${y+24}" text-anchor="middle">${fmt(v)}</text>`:''}`});
  g+=`<circle cx="${fx(an[0])}" cy="${y}" r="6" fill="#d8894f"/><text x="${fx(an[0])}" y="${y-13}" text-anchor="middle" style="fill:var(--ink)">${fmt(an[1])}</text>
    <text x="${fx(an[0])}" y="${y+24}" text-anchor="middle" style="fill:#d8894f">${fmt(an[0])}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(key)} sweep: one anchor, ${sealed.length} sealed">${g}</svg>
   <p class="cs"><span style="color:#d8894f">●</span> anchor: ${esc(q)} = ${fmt(an[1])} at ${esc(key)} = ${fmt(an[0])} · ? ${sealed.length} sealed point${sealed.length>1?'s':''}, scored only by the benchmark</p>`}
function triageBox(P){const t=P.triage;if(!t)return P.triage_error?`<div class="callout warn" style="margin-bottom:12px">Paper-index triage failed: ${esc(P.triage_error)}</div>`:'';
  const ps=t.papers||[];if(!ps.length)return '';
  const row=p=>`<li><a href="${esc(p.url||'#')}" target="_blank" rel="noopener">${esc(p.title)}</a>
    <span class="tmeta">${esc([p.year,p.venue].filter(Boolean).join(' · '))}${p.citations!=null?` · ${p.citations} cites`:''}</span>
    <span class="tk ${esc(p.kind)}">${esc(p.kind)}</span>${p.verified===true?'<span class="tv ok" title="DOI and title confirmed by CrossRef">DOI ✓</span>':p.doi?'<span class="tv" title="DOI not confirmed by CrossRef">DOI ?</span>':''}
    <div class="twhy">${esc(p.reports||p.why)}</div></li>`;
  return `<details class="triage" open><summary>Paper-index triage · ${ps.length} papers to open first${(t.counts||[]).map(c=>` · ${c.n.toLocaleString()} on “${esc(c.query)}”`).join('')}</summary>
    ${t.reply?`<p class="treply">${esc(t.reply)}</p>`:''}<ol>${ps.map(row).join('')}</ol>
    <p class="tnote">Leads from an index of abstracts (${esc(t.backend)}); the scout reads the papers for conditions and numbers.${t.note?' '+esc(t.note):''}</p></details>`}
function pPrior(s,P){const st=P.studies||[];if(!st.length)return wait(s.busy||'Looking for related studies.');
  const pb=s.problem;const qs=[...new Set([...Object.keys(pb.targets||{}),'size_mean_nm'])];const q=qs.includes(AG.qtab)?AG.qtab:qs[0];
  const n={benchmark:0,library:0,web:0};st.forEach(x=>n[x.source]++);
  return `<div class="apanel"><h3>Related studies</h3><p class="sub">${n.benchmark} benchmark cases (blind: their outcomes stay sealed until the stack is scored), ${n.library} from the mined library, ${n.web} from the literature (read by the agent, not verified). Sorted by relevance to your goal.</p>
   ${P.web_reply?`<div class="callout info" style="margin-bottom:12px">${esc(P.web_reply)}</div>`:''}${P.web_error?`<div class="callout warn" style="margin-bottom:12px">Literature search failed: ${esc(P.web_error)}</div>`:''}${triageBox(P)}
   <div class="ctabs">${qs.map(z=>`<button class="chip ${z===q?'on':''}" type="button" data-qt="${z}">${esc(z)}</button>`).join('')}</div>
   <div class="agrid">${st.map(x=>studyBox(x,q)).join('')}</div></div>`}
STEP_PANELS.prior = pPrior;
