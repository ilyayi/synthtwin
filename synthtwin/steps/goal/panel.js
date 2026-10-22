/* The goal step's panel: the measurable goal the agent wrote (targets on range
   bars, knobs, fixed conditions) and what is still missing. Loads before
   agent.js but only runs once the whole page is up (AG, wait, icon, fmt, esc
   come from agent.js / common.js). */
const qn=q=>(AG.meta?.quantities||{})[q]||q;
const tgtTxt=t=>[t.value!=null?'= '+fmt(t.value):'',t.min!=null?'≥ '+fmt(t.min):'',t.max!=null?'≤ '+fmt(t.max):''].filter(Boolean).join(', ');

/* ---- goal */
const tgtIcon=q=>{q=q.toLowerCase();
  if(/cv|sd\b|_sd|pdi|fwhm|width|spread/.test(q))return 'spread';
  if(/lspr|pl_|absorb|wavelength|spectr|uv/.test(q))return 'spectrum';
  if(/size|diameter|length|thickness|d_/.test(q))return 'ruler';
  return 'target'};
/* the target value or band on a small range bar (the scale is the target itself ± headroom) */
function rangeBar(t){
  const vs=[t.value,t.min,t.max].filter(v=>v!=null);if(!vs.length)return '';
  const lo0=Math.min(...vs),hi0=Math.max(...vs),span=(hi0-lo0)||Math.abs(hi0)||1;
  const lo=lo0-span*.45,hi=hi0+span*.45,X=v=>Math.max(0,Math.min(100,(v-lo)/(hi-lo)*100));
  const band=t.min!=null||t.max!=null?`<i class="band" style="left:${X(t.min??lo)}%;width:${X(t.max??hi)-X(t.min??lo)}%"></i>`:'';
  const mark=t.value!=null?`<i class="mark" style="left:${X(t.value)}%"></i>`:'';
  return `<span class="tbar">${band}${mark}</span>`}
function pGoal(s,P){const pb=s.problem||{};
  if(!pb.material&&!Object.keys(pb.targets||{}).length)return wait('The agent is reading your problem.');
  const lim=AG.s&&s.phases.goal.notes||[];
  return `<div class="apanel"><h3>Measurable goal</h3><p class="sub">What the study optimises for. Change anything by telling the agent in the chat.</p>
   <div class="agrid">
    <div class="abox"><h4>Targets</h4>${Object.entries(pb.targets||{}).map(([q,t])=>`<div class="tgcard">${icon(tgtIcon(q),'tg2')}<div class="tgc">
      <div class="row"><span class="pill">${esc(q)}</span><b>${esc(tgtTxt(t))}</b></div>
      <p class="help" style="margin:2px 0 0">${esc(qn(q))}</p>${rangeBar(t)}</div></div>`).join('')||'<p class="help">none yet</p>'}</div>
    <div class="abox"><h4>Knobs the optimiser may change</h4>${Object.entries(pb.knobs||{}).map(([k,r])=>`<div class="row"><span class="pill">${esc(k)}</span><b>${fmt(r[0])} – ${fmt(r[1])}</b></div>`).join('')||'<p class="help">none yet</p>'}</div>
    <div class="abox"><h4>Held fixed</h4>${Object.entries(pb.fixed||{}).map(([k,v])=>`<div class="row"><span class="pill">${esc(k)}</span><b>${fmt(v)}</b></div>`).join('')||'<p class="help">nothing yet (defaults are added on confirm)</p>'}
     <dl class="kvt" style="margin-top:6px"><dt>material</dt><dd>${esc(pb.material||'—')}</dd><dt>method</dt><dd>${esc(pb.method||'—')}</dd></dl></div>
   </div>
   ${(P.errors||[]).length?`<div class="callout warn" style="margin-top:12px">Not complete yet: ${esc(P.errors.join('; '))}</div>`:''}
   ${lim.length?`<div class="callout info" style="margin-top:12px">On confirm: ${esc(lim.join('; '))}</div>`:''}</div>`}
STEP_PANELS.goal = pGoal;
