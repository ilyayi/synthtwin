/* The sample step's panel: the related studies the stack must predict before
   it is trusted, with the researcher's picks. esc and fmt come from
   common.js; the blind pill and relevance bar are shared shell styles. */
/* ---- sample */
function pSample(s,P,live){const cs=P.candidates||[];
  if(!cs.length)return `<div class="apanel"><h3>Benchmark sample</h3><p class="sub">No related study has enough data points to test the stack on. Confirm to go on without a benchmark: your case then runs as exploratory (ask the agent for a narrower literature search first if you want one).</p></div>`;
  return `<div class="apanel"><h3>Benchmark sample</h3><p class="sub">The stack will predict these studies before it predicts yours. Blind ones are scored against outcomes it has never seen; literature ones are not blind.</p>
   <div class="agrid">${cs.map(c=>`<label class="abox ${c.selected?'sel':''}" style="cursor:pointer"><div class="row"><input type="checkbox" data-c="${esc(c.id)}" ${c.selected?'checked':''} ${live?'':'disabled'}>
     ${c.blind?'<span class="pill blind">blind</span>':'<span class="pill web">not blind</span>'}<span class="pill">${c.n_points} points</span><span class="pill">sweeps ${esc(c.swept_key)}</span></div>
     <h4>${esc(c.title)}</h4><div class="relbar"><i style="width:${Math.round(c.relevance*100)}%"></i></div><p class="help" style="margin:0">${esc(c.material)} · ${esc(c.method)} · relevance ${fmt(c.relevance)}</p></label>`).join('')}</div></div>`}
STEP_PANELS.sample = pSample;
