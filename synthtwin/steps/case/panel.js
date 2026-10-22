/* The case step's panel: the tornado of knob sensitivities, the 2-D map with
   the optimiser's proposals, one-knob sweeps with bands, the agent's
   insights and the "Why 60/40" benchmark card. AG, wait, esc, fmt, lineChart,
   tornado and heatmap come from agent.js / common.js. */
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
  const pills=(P.proposals||[]).filter(p=>p.policy).map(p=>`<span class="pill ${p.policy==='exploit'?'blind':'web'}" title="${p.policy==='exploit'?'best predicted score':'widest model band: the measurement teaches the model most'}">${esc(p.id.split('-').pop())} ${p.policy==='exploit'?'exploit · best predicted':'explore · most uncertain'}</span>`).join('');
  return `<div class="apanel"><h3>Your case</h3><p class="sub">${esc((P.basis?.why||[]).join(' · '))} · ${P.basis?.label==='validated'?'<span class="pill blind">validated stack</span>':'<span class="pill web">exploratory: the benchmark did not validate the stack</span>'} · ${fmt(P.seconds)} s</p>
   ${(P.insights||[]).length?`<div class="callout info" style="margin-bottom:14px"><b>What the simulations say</b><ul class="insights" style="margin-top:6px">${P.insights.map(i=>`<li>${esc(i)}</li>`).join('')}</ul></div>`:''}
   <div class="charts">
    <div class="chart"><p class="ct">Which knob moves ${esc(q)} most</p><p class="cs">range of ${esc(q)} over each knob's range, others at mid-range (centre ${fmt(P.center?.value)})</p>${tornado(P.tornado,P.center?.value,tb)}</div>
    ${H?`<div class="chart"><p class="ct">${esc(q)} over ${esc(H.x_key)} × ${esc(H.y_key)}</p><p class="cs">cyan line: your target; dots: proposed recipes</p>${heatmap(H,(P.proposals||[]).map(p=>[p.conditions[H.x_key],p.conditions[H.y_key],p.id]))}</div>`:''}
   </div>
   <div class="ctabs" style="margin-top:14px">${ks.map(x=>`<button class="chip ${x===k?'on':''}" type="button" data-kt="${esc(x)}">${esc(x)}</button>`).join('')}</div>
   <div class="charts">${lines}</div>
   ${pills?`<div class="row" style="margin-top:12px;flex-wrap:wrap;gap:6px"><span class="cs">how the optimiser splits its ${P.proposals.length} proposals:</span>${pills}</div>`:''}
   <div class="bx-card" data-bx><div data-bxin>${BX.data?bxCard(BX.data,BX.ds):'<p class="cs">loading the 60/40 benchmark…</p>'}</div></div></div>`}
STEP_PANELS.case = pCase;

/* ---- the "Why 60/40" card: results of the literature-campaign benchmark
   (bench6040.py) served by /api/bench6040. Series colors are entity-locked and
   validated for the dark panel surface; random is dashed as a second cue. */
const BX={ds:'AgNP',data:null,promise:null};
const BX_SERIES=[['60/40','#c06a35',true,false],['random','#5c6cb0',false,true],['exploit','#b98d33',false,false],['explore','#8d66c9',false,false],['EI','#279871',false,false]];

function bxN(v,budget){return v>budget?`>${budget}`:`${v}`}   // censored medians

function bxCard(json,ds){
  if(json.error||!json.datasets||!json.datasets[ds])return `<p class="cs">${esc(json.error||'no benchmark data')}</p>`;
  const d=json.datasets[ds],c=d.curves,mine=c['60/40'],rnd=c.random;
  const dir=d.direction==='max'?'higher is better':'lower is better';
  const series=BX_SERIES.filter(s=>c[s[0]]).map(([n,col,band,dash])=>({color:col,label:n,band,dash,
    pts:c[n].ns.map((x,i)=>[x,c[n].mean[i],band?c[n].p5[i]:null,band?c[n].p95[i]:null])}));
  const tabs=Object.keys(json.datasets).map(x=>`<button class="chip ${x===ds?'on':''}" type="button" data-bxd="${esc(x)}">${esc(x)}</button>`).join('');
  const stats=[['60/40 to top 1 %',bxN(mine.n_top1,d.budget)],['random to top 1 %',bxN(rnd.n_top1,d.budget)],
    ['EF vs random',`${(+mine.ef_top1).toFixed(1)}×`],['hits the literature optimum',`${Math.round(mine.hit_rate*100)} %`]]
    .map(([k,v])=>`<span class="bx-stat"><b>${esc(v)}</b> ${esc(k)}</span>`).join('');
  return `<p class="ct">Why 60/40 · ${esc(ds)}</p>
   <p class="cs">best-so-far ${esc(d.objective)} vs experiments run (${dir}); mean over ${json.meta.setup.seeds} seeds, band: 5-95 % on 60/40 · pool: ${d.n_pool} measured conditions from ${d.n_raw} rows · ${esc(json.meta.cite.split(',')[0])} et al. 2021, MIT</p>
   <div class="ctabs" style="margin:8px 0">${tabs}</div>
   ${lineChart({w:760,h:280,xlab:'experiments',ylab:d.objective,series})}
   ${legend(series)}
   <div class="bx-stats">${stats}</div>
   <p class="cs" style="margin:0">${bxVerdict(ds,d)}</p>`;
}

function bxVerdict(ds,d){
  const c=d.curves,mine=c['60/40'],rnd=c.random;
  const others=Object.entries(c).filter(([k])=>k!=='60/40');
  const best=Math.min(mine.n_top1,...others.map(([,v])=>v.n_top1));
  const faster=Object.keys(c).filter(k=>k!=='60/40'&&k!=='random'&&c[k].n_top1<mine.n_top1);
  const censored=mine.n_top1>d.budget;
  const head=`On ${ds}, 60/40 reaches the top 1 % of the pool in a median of ${bxN(mine.n_top1,d.budget)} of ${d.budget} experiments (random: ${bxN(rnd.n_top1,d.budget)}, enhancement ${(+mine.ef_top1).toFixed(1)}×)`;
  if(censored)return `${head}, but neither it nor random got there within budget on half the seeds.`;
  const tail=faster.length?`; here ${faster.join(' and ')} ${faster.length>1?'are':'is'} faster at ${best}.`:` — as fast as the best strategy tried.`;
  return `${head}${tail}`;
}

STEP_BINDS.case=(s,P)=>{const box=document.querySelector('[data-bx]');if(!box)return;
  box.onclick=e=>{const b=e.target.closest('[data-bxd]');if(b&&BX.data){BX.ds=b.dataset.bxd;box.querySelector('[data-bxin]').innerHTML=bxCard(BX.data,BX.ds)}};
  if(BX.data&&box.querySelector('[data-bxin] .cs'))box.querySelector('[data-bxin]').innerHTML=bxCard(BX.data,BX.ds);   // the page re-rendered while the fetch ran
  if(!BX.promise)BX.promise=fetch('/api/bench6040').then(r=>r.json()).then(j=>{BX.data=j;
    const inn=document.querySelector('[data-bx] [data-bxin]');if(inn)inn.innerHTML=bxCard(j,BX.ds)})
    .catch(()=>{BX.data={error:'benchmark data unavailable'};   // show it, never stay on 'loading'
      const inn=document.querySelector('[data-bx] [data-bxin]');if(inn)inn.innerHTML=bxCard(BX.data,BX.ds)});
};
