/* The case step's panel: the tornado of knob sensitivities, the 2-D map with
   the optimiser's proposals, one-knob sweeps with bands and the agent's
   insights. AG, wait, esc, fmt, lineChart, tornado and heatmap come from
   agent.js / common.js. */
/* ---- case */
function pCase(s,P){if(P.unsupported)return `<div class="apanel"><h3>Your case</h3><p class="sub">No runnable simulator for ${esc(s.problem.material)} yet; see the chat for what would be needed.</p></div>`;
  if(!P.tornado)return wait(s.busy||'Simulating your case.');
  const pb=s.problem,q=P.primary,t=pb.targets[q]||{};const ks=Object.keys(P.sweeps||{});const k=ks.includes(AG.ktab)?AG.ktab:(P.tornado[0]||{}).knob||ks[0];
  const sw=P.sweeps[k];const qs=P.quantities||[q];
  const tb=t.value!=null?{lo:t.value,hi:t.value}:{lo:t.min,hi:t.max};
  const lines=qs.filter(z=>sw[z]&&sw[z].some(Boolean)).map(z=>`<div class="chart"><p class="ct">${esc(z)} vs ${esc(k)}</p><p class="cs">other knobs at mid-range; shaded: model band${pb.targets[z]?' · cyan: your target':''}</p>
    ${lineChart({w:360,h:220,xlab:k,ylab:z,series:[{color:'#d8894f',band:true,pts:sw.x.map((x,i)=>sw[z][i]?[x,sw[z][i].value,sw[z][i].low,sw[z][i].high]:null).filter(Boolean)}],
      target:pb.targets[z]?(pb.targets[z].value!=null?{lo:pb.targets[z].value,hi:pb.targets[z].value}:{lo:pb.targets[z].min,hi:pb.targets[z].max}):null,
      points:(P.proposals||[]).map(p=>[p.conditions[k],(p.predicted[z]||{}).value]).filter(p=>p[0]!=null&&p[1]!=null)})}</div>`).join('');
  const H=P.heatmap;
  return `<div class="apanel"><h3>Your case</h3><p class="sub">${esc((P.basis?.why||[]).join(' · '))} · ${P.basis?.label==='validated'?'<span class="pill blind">validated stack</span>':'<span class="pill web">exploratory: the benchmark did not validate the stack</span>'} · ${fmt(P.seconds)} s</p>
   ${(P.insights||[]).length?`<div class="callout info" style="margin-bottom:14px"><b>What the simulations say</b><ul class="insights" style="margin-top:6px">${P.insights.map(i=>`<li>${esc(i)}</li>`).join('')}</ul></div>`:''}
   <div class="charts">
    <div class="chart"><p class="ct">Which knob moves ${esc(q)} most</p><p class="cs">range of ${esc(q)} over each knob's range, others at mid-range (centre ${fmt(P.center?.value)})</p>${tornado(P.tornado,P.center?.value,tb)}</div>
    ${H?`<div class="chart"><p class="ct">${esc(q)} over ${esc(H.x_key)} × ${esc(H.y_key)}</p><p class="cs">cyan line: your target; dots: proposed recipes</p>${heatmap(H,(P.proposals||[]).map(p=>[p.conditions[H.x_key],p.conditions[H.y_key],p.id]))}</div>`:''}
   </div>
   <div class="ctabs" style="margin-top:14px">${ks.map(x=>`<button class="chip ${x===k?'on':''}" type="button" data-kt="${esc(x)}">${esc(x)}</button>`).join('')}</div>
   <div class="charts">${lines}</div></div>`}
STEP_PANELS.case = pCase;
