/* The recipe step's panel: the agent's write-up (steps, checks, risks), the
   optimiser's proposals to pick from, and the predicted spectrum of the best
   one. AG, wait, esc, fmt, lineChart and hist come from agent.js / common.js. */
/* ---- recipe */
function pRecipe(s,P,live){const C=s.phases.case;const props=C.proposals||[];const R=P.recipe;
  if(!props.length&&!R)return wait(s.busy||'Writing the recipe.');
  const ch=P.choice||(props[0]||{}).id||'agent';const sp=props.length?C.spectrum:null;
  const tc=sp&&sp.time_course;
  const specCharts=sp?`<div class="charts" style="margin-top:14px">
    ${sp.wavelength_nm?`<div class="chart"><p class="ct">Predicted UV-Vis of ${esc(props[0].id.split('-').pop())}</p><p class="cs">LSPR ${fmt(sp.lspr_nm)} nm; what the robot's spectrometer should show</p>
      ${lineChart({w:360,h:200,xlab:'wavelength (nm)',ylab:'absorbance',series:[{color:'#62c6f2',band:!!sp.absorbance_low,pts:sp.wavelength_nm.map((w,i)=>[w,sp.absorbance[i],sp.absorbance_low?.[i],sp.absorbance_high?.[i]])}],vline:sp.lspr_nm})}</div>`:''}
    ${sp.d_centers_nm?`<div class="chart"><p class="ct">Predicted size distribution</p><p class="cs">number distribution of core diameters</p>${hist(sp.d_centers_nm,sp.number_per_m3)}</div>`:''}
    ${tc&&tc.t_s?`<div class="chart"><p class="ct">How the particles form</p><p class="cs">mean diameter (copper) and precursor left (cyan, right scale) over time</p>
      ${lineChart({w:360,h:200,xlab:'time (s)',ylab:'mean d (nm)',logx:tc.t_s[0]>0,series:[{color:'#d8894f',pts:tc.t_s.map((t,i)=>[t,tc.mean_d_nm[i]]).filter(p=>p[0]>0&&p[1]>0)}],
        y2:{label:'precursor (mM)',color:'#62c6f2',pts:tc.t_s.map((t,i)=>[t,tc.precursor_mM[i]]).filter(p=>p[0]>0)}})}</div>`:''}</div>`:'';
  return `<div class="apanel recipe"><h3>Recipe</h3><p class="sub">${R?esc(R.why):'The agent is writing it up.'}</p>
   ${R?`<div class="agrid" style="grid-template-columns:minmax(0,1.4fr) minmax(0,1fr)"><div class="abox"><h4>${esc(R.title)}</h4><ol>${(R.steps||[]).map(x=>`<li>${esc(x.replace(/^\s*\d+[.)]\s*/,''))}</li>`).join('')}</ol></div>
     <div class="abox"><h4>Expected</h4><p>${esc(R.expected)}</p><h4>Quick checks on the robot</h4><ul>${(R.checks||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul><h4>Risks</h4><ul>${(R.risks||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>${R.alternatives?`<p class="help">${esc(R.alternatives)}</p>`:''}</div></div>`:''}
   <h4 style="margin:18px 0 8px">What to send to the robot</h4>
   ${props.length?'':'<p class="help" style="margin:0 0 8px">The optimiser found no recipe that meets the target in your ranges, so the only option is the agent\'s write-up above. It has no model band.</p>'}
   <div class="agrid">${R?`<label class="abox ${ch==='agent'?'sel':''}" style="cursor:pointer"><div class="row"><input type="radio" name="agprop" value="agent" ${ch==='agent'?'checked':''} ${live?'':'disabled'}><b>The agent's recipe</b><span class="pill web">agent recipe</span></div><p>${esc(R.title)}</p></label>`:''}${props.map(p=>`<label class="abox ${p.id===ch?'sel':''}" style="cursor:pointer"><div class="row"><input type="radio" name="agprop" value="${esc(p.id)}" ${p.id===ch?'checked':''} ${live?'':'disabled'}><b class="mono" title="${esc(p.id)}">${esc(p.id.split('-').pop())}</b>
      <span class="pill ${p.label==='exploratory'?'web':'blind'}">${esc(p.label)}</span>${p.policy?`<span class="pill ${p.policy==='exploit'?'blind':'web'}" title="${p.policy==='exploit'?'best predicted score':'widest model band: the measurement teaches the model most'}">${p.policy==='exploit'?'exploit · best predicted':'explore · most uncertain'}</span>`:''}<span class="pill">${p.novelty?.novel?'novel':'near known work'}</span></div>
     <div class="row">${Object.entries(p.conditions).map(([k,v])=>`<span class="pill p">${esc(k)}=${fmt(v)}</span>`).join('')}</div>
     <div class="row">${Object.entries(p.predicted).map(([q,b])=>`<span class="pill">${esc(q)} ${fmt(b.value)} [${fmt(b.low)}–${fmt(b.high)}]</span>`).join('')}</div></label>`).join('')}</div>
   ${(C.dropped||[]).length?`<details class="more" data-k="dropped"><summary>${C.dropped.length} candidates dropped</summary><div class="inner"><ul style="margin:0;padding-left:18px">${C.dropped.map(d=>`<li><span class="mono">${esc(Object.entries(d.conditions).map(([k,v])=>k+'='+fmt(v)).join(', '))}</span>: ${esc(d.why)}</li>`).join('')}</ul></div></details>`:''}
   ${specCharts}</div>`}
STEP_PANELS.recipe = pRecipe;
