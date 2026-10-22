/* The stack step's panel: the three-scale view of the stack (reactor ->
   molecular -> atomistic), its chain of physics, its visuals, and the method
   table with the researcher's ticks. AG, wait, icon, fmt, esc and the charts
   come from agent.js / common.js. */
const STATUS_ORDER=['runnable','cached','literature','queued','planned'];
const STATUS_WORD={runnable:'runs here now',cached:'cached results',literature:'looked up',queued:'would run on the GPU pool',planned:'not built yet'};
const dur=s=>s<90?`${Math.round(s)} s`:s<5400?`${Math.round(s/60)} min`:s<172800?`${(s/3600).toFixed(s<36000?1:0)} h`:`${Math.round(s/86400)} days`;

/* formula text -> HTML: _x / _{xy} -> sub, ^x / ^{xy} -> sup (unicode Greek and operators pass through) */
function fmtFormula(f){return esc(f)
  .replace(/\^\{([^}]*)\}/g,'<sup>$1</sup>').replace(/\^([A-Za-z0-9+\-−–])/g,'<sup>$1</sup>')
  .replace(/_\{([^}]*)\}/g,'<sub>$1</sub>').replace(/_([A-Za-z0-9+\-−–])/g,'<sub>$1</sub>')}

/* ---- stack */
/* the three scales of the same stack: reactor -> molecular -> atomistic, each with its own visual */
const SCALE_ORDER=['reactor','molecular','atomistic'];
const SCALE_META={
 reactor:{name:'Reactor',icon:'vessel',ruler:'cm · s–min',col:'#d8894f',
   title:'Reactor: the vessel and its process',summary:'The vessel and its process — heating, stirring, dosing, evaporation, flow — set the temperature, mixing and concentrations the liquid actually sees.',
   assumed:'assumed well-mixed and isothermal; a vessel-process or CFD method (OpenFOAM, FEniCS) would cover it'},
 molecular:{name:'Molecular',icon:'molecule',ruler:'nm · ms–min',col:'#62c6f2',
   title:'Molecular: what the conditions do to the liquid',summary:'Those conditions drive the molecules and particles in the liquid: speciation, reaction kinetics, nucleation, growth and ripening — and the optical readout they produce.',
   assumed:'assumed from literature rates; a kinetics or population-balance method would cover it'},
 atomistic:{name:'Atomistic',icon:'atom',ruler:'Å · ps',col:'#4fd39a',
   title:'Atomistic: the interactions between atoms',summary:'The interactions between the atoms themselves — bonding, surface and ligand binding energies, coalescence — supply the constants the larger scales need.',
   assumed:'assumed from published values; DFT or MD would cover it'}};
const TOOL_GLYPH=[[/lammps|\bmd\b|molecular dynamics/,'atom'],[/xtb/,'bond'],[/espresso|dft|ab initio|psi4|orca/,'electron'],
 [/fenics|fem|dolfin/,'mesh'],[/cantera|mkin|microkin/,'reaction'],[/openfoam|cfd|fluid/,'flow'],
 [/deepmd|\bml\b|learn|gp$|sklearn/,'ml'],[/python|numpy|scipy|pandas/,'code']];
const toolGlyph=t=>{t=String(t||'').toLowerCase();for(const[r,g]of TOOL_GLYPH)if(r.test(t))return g;return 'code'};
const LINK_ICON=[[/speciat/,'molecule'],[/vessel|well|reactor/,'vessel'],[/reduc|reaction|kinetic/,'reaction'],
 [/nucleat|burst/,'nucleus'],[/growth|ripen|coalesc/,'growth'],[/surface|faceting|shape/,'crystal'],
 [/optic|readout|spectrum|pl_|lspr|uv/,'spectrum'],[/search|fit|calibrat/,'chart']];
const linkIcon=(id,name)=>{const t=(id+' '+name).toLowerCase();for(const[r,i]of LINK_ICON)if(r.test(t))return i;return 'chart'};

/* a method's scale, from the catalog's own scale text or the generic method's scale field */
function methodClass(m,md){
  const sc=String(m.scale||(md||{}).scale||'').toLowerCase();
  const txt=(String(m.name||(md||{}).name||'')+' '+String(m.role||(md||{}).gives||'')+' '+sc).toLowerCase();
  if(sc==='data'||/bayes|optimi[sz]|recipe space|residual|surrogate/.test(txt))return 'data';
  if(/population|pbm|mesoscal|phase.field|readout|optic|kinetic|speciation|dls|spectrum/.test(txt))return 'molecular';
  if(/mixing|\bcfd\b|openfoam|vessel|well plate|evaporat|residence|stirr/.test(txt))return 'reactor';
  if(/reactor/.test(sc)&&!/population/.test(txt))return 'reactor';
  if(/atom|dft|xtb|reaxff|mlip|deepmd|aimd|electronic|\bmd\b/.test(txt))return 'atomistic';
  if(/particle|cluster|ensemble/.test(txt))return 'molecular';
  return 'molecular'}

/* the scales, from the LLM's own answer or built from the methods and chain (old studies) */
function buildScales(s,P){
  const meta=Object.fromEntries((AG.meta.methods||[]).map(m=>[m.id,m]));
  const cls=m=>methodClass(m,meta[m.id]);
  const out={};
  SCALE_ORDER.forEach(id=>out[id]={id,title:SCALE_META[id].title,summary:SCALE_META[id].summary,
    size:SCALE_META[id].ruler.split(' · ')[0],time:SCALE_META[id].ruler.split(' · ')[1],
    processes:[],links:[],methods:[],built:true});
  (P.methods||[]).forEach(m=>{const k=cls(m);if(k!=='data')out[k].methods.push(m.id)});
  (P.chain||[]).forEach(c=>{                       // a link sits at every scale one of its methods covers
    const ks=[...new Set((c.methods||[]).map(id=>{const m=(P.methods||[]).find(x=>x.id===id);return m?cls(m):null})
      .filter(k=>k&&out[k]))];                      // 'data' methods are the learning layer, not a scale
    ks.forEach(k=>{if(!out[k].links.includes(c.id))out[k].links.push(c.id)});
    if(ks.length)                                   // fallback cards get process chips from the links
      out[ks[0]].processes.push({name:c.name,what:String(c.physics||'').slice(0,140),
        icon:linkIcon(c.id,c.name),formula:''})});
  SCALE_ORDER.forEach(id=>{const o=out[id];
    o.processes=o.processes.slice(0,5);
    o.assumed=!o.methods.length&&!o.links.length;});
  return out}
function scalesOf(s,P){                            // the stored scales, with any missing one filled in
  const built=buildScales(s,P),have={};
  (P.scales||[]).forEach(x=>have[x.id]=x);
  return SCALE_ORDER.map(id=>have[id]||built[id]).filter(Boolean)}

/* simulation visuals: /api/viz items for this study, per scale */
function studyVizKey(s){const t=((s.problem||{}).material||'')+' '+(s.title||'');
  if(/\bcds\b|cadmium sulfide/i.test(t))return 'cds';if(/\b(gold|au)\b/i.test(t))return 'gold';return null}
const isVid=f=>/\.(mp4|webm)$/i.test(f||'');
function vizFor(s,P,sc){
  const zs=scalesOf(s,P),ch=P.chain||[];
  const hit=(v,z)=>v.scale?v.scale===z.id:!!v.link&&(z.links||[]).some(id=>id===v.link
    ||String((ch.find(c=>c.id===id)||{}).name||'').toLowerCase().includes(String(v.link).toLowerCase()));
  const k=studyVizKey(s),links=sc.links||[];
  return (AG.viz&&AG.viz.items||[])
    .filter(v=>v&&v.file&&(v.scale||v.link)&&(!k||!v.study||v.study===k))
    .filter(v=>{for(let i=SCALE_ORDER.length-1;i>=0;i--){const z=zs.find(x=>x.id===SCALE_ORDER[i]);
      if(z&&hit(v,z))return z.id===sc.id}return false})   // when several scales match, the deepest wins
    .sort((a,b)=>(links.includes(b.link)?1:0)-(links.includes(a.link)?1:0)||(isVid(b.file)?1:0)-(isVid(a.file)?1:0))}

/* an illustrative diagram when no simulation visual exists: clearly a schematic, no numbers */
function schematic(id){
  const c=SCALE_META[id].col;
  if(id==='reactor')return `<svg viewBox="0 0 320 180" class="schemsvg" role="img" aria-label="schematic: a stirred, heated flask">
   <g fill="none" stroke="${c}" stroke-width="1.6" stroke-linecap="round">
    <path d="M138 26h44M146 26v34M174 26v34" opacity=".9"/>
    <circle cx="160" cy="112" r="46" opacity=".9"/>
    <path d="M126 100h68" opacity=".55"/>
    <path d="M141 128c6-5 32-5 38 0" opacity=".55"/>
    <rect x="146" y="107" width="28" height="8" rx="4" transform="rotate(-16 160 111)" opacity=".95"/>
    <path d="M138 92c-5-6 5-12 0-18M182 92c-5-6 5-12 0-18" opacity=".5"/>
    <path d="M128 172c6-8 18-8 24 0M152 172c6-8 18-8 24 0M176 172c6-8 18-8 24 0" opacity=".8"/>
    <path d="M232 60c14 4 22 14 22 28M232 60l10 2M232 60l3 10" opacity=".7"/>
    <path d="M252 44c1.9 2.4 3.2 4 3.2 5.9a3.2 3.2 0 0 1-6.4 0c0-1.9 1.3-3.5 3.2-5.9z" opacity=".9"/>
    <path d="M232 132c14-4 22-14 22-28M232 132l10-2M232 132l3-10" opacity=".7"/>
   </g></svg>`;
  if(id==='molecular')return `<svg viewBox="0 0 320 180" class="schemsvg" role="img" aria-label="schematic: particles and molecules in a liquid">
   <g fill="none" stroke="${c}" stroke-width="1.6" stroke-linecap="round">
    <rect x="30" y="24" width="260" height="132" rx="14" opacity=".45"/>
    <g opacity=".35"><path d="M60 50h14M92 44h10M230 60h16M70 130h12M250 128h12M110 150h14"/></g>
    <circle cx="96" cy="86" r="26" opacity=".95"/><circle cx="96" cy="86" r="31" stroke-dasharray="2 5" opacity=".4"/>
    <circle cx="182" cy="60" r="14" opacity=".9"/><circle cx="206" cy="104" r="19" opacity=".9"/>
    <circle cx="146" cy="132" r="9" opacity=".8"/><circle cx="240" cy="146" r="7" opacity=".7"/>
    <circle cx="58" cy="118" r="7" opacity=".7"/>
    <path d="M56 74l-8-6M64 68l-2-10" opacity=".7"/><path d="M222 78l9 5M231 68l9 1" opacity=".7"/>
    <circle cx="130" cy="62" r="4.4"/><circle cx="141" cy="68" r="4.4"/><path d="M133.5 64l3 2" opacity=".9"/>
    <circle cx="72" cy="66" r="4.4"/><circle cx="62" cy="72" r="4.4"/><path d="M67.8 68.2l-1.6 1.6" opacity=".9"/>
   </g></svg>`;
  return `<svg viewBox="0 0 320 180" class="schemsvg" role="img" aria-label="schematic: atoms, bonds and a ligand shell">
   <g fill="none" stroke="${c}" stroke-width="1.6" stroke-linecap="round">
    <path d="M96 56l34 20v40l-34 20-34-20V76z" opacity=".9"/>
    <path d="M96 56v80M62 76l68 40M130 76 62 116" opacity=".45"/>
    <circle cx="168" cy="96" r="34" opacity=".95"/>
    <path d="M156 72l-8-12M180 70l6-13M192 90l13-4M190 114l12 7M168 130v13M146 118l-10 10M144 84l-13-5" opacity=".8"/>
    <g fill="${c}" stroke="none" opacity=".95"><circle cx="145" cy="56" r="3"/><circle cx="188" cy="53" r="3"/><circle cx="209" cy="84" r="3"/><circle cx="206" cy="124" r="3"/><circle cx="168" cy="147" r="3"/><circle cx="133" cy="132" r="3"/><circle cx="129" cy="77" r="3"/></g>
    <path d="M236 46h30M236 46l6-5M236 46l6 5" opacity=".7"/><path d="M266 46h-8" opacity=".4"/>
   </g></svg>`}

/* the visual for one scale: a simulation clip/still when there is one, else the schematic */
const RM=matchMedia('(prefers-reduced-motion: reduce)').matches;
function vizBox(s,P,sc){
  const items=vizFor(s,P,sc);
  if(!items.length)return `<div class="schem" aria-label="schematic">${schematic(sc.id)}<span class="pill p">schematic</span></div>`;
  const i=Math.min(AG.vtab[sc.id]||0,items.length-1),it=items[i];
  const src=esc('/viz/'+it.file),poster=it.poster?esc('/viz/'+it.poster):'';
  const vid=isVid(it.file);
  const media=vid&&!RM?`<video autoplay muted loop playsinline preload="metadata"${poster?` poster="${poster}"`:''} src="${src}"></video>`
    :vid?`<img src="${poster||src}" alt="" ${poster?`data-vsrc="${src}"`:''}>`
    :`<img src="${src}" alt="">`;
  const play=vid&&RM?`<span class="splay">${icon('play')}</span>`:'<span class="splay svis-expand">'+icon('play')+'</span>';
  return `<figure class="sviz">
   <button class="svbox" type="button" data-viz="${sc.id}:${i}" aria-label="open ${esc(it.title||'the visual')} full screen">${media}${play}</button>
   <figcaption><span class="pill ${it.kind==='model-input'?'web':'blind'}">${it.kind==='model-input'?'model input':'simulated result'}</span>
    <b>${esc(it.title||'')}</b> <span class="cap">${esc(it.caption||'')}</span></figcaption>
   ${items.length>1?`<div class="sthumbs">${items.map((x,j)=>`<button class="sthumb ${j===i?'on':''}" type="button" data-vtab="${sc.id}:${j}" aria-label="${esc(x.title||'visual '+(j+1))}">${x.poster?`<img src="/viz/${esc(x.poster)}" alt="">`:`<span>${vid?'▶':'◫'}</span>`}</button>`).join('')}</div>`:''}
  </figure>`}

/* one scale card: icon, title, size/time, summary, processes, visual, methods, links */
function scaleCard(s,P,sc,i,n){
  const M=SCALE_META[sc.id],meta=Object.fromEntries((AG.meta.methods||[]).map(m=>[m.id,m]));
  const generic=P.methods&&P.methods[0]&&P.methods[0].tool!==undefined;
  const byId=id=>(P.methods||[]).find(m=>m.id===id);
  const ids=(sc.methods||[]).filter(id=>byId(id));
  const used=ids.length?ids:(sc.built?(P.methods||[]).filter(m=>methodClass(m,meta[m.id])===sc.id).map(m=>m.id):[]);
  const STATUS={runnable:'runs now',cached:'runs now',literature:'runs now',queued:'queued',planned:'planned'};
  const meth=used.map(id=>{const m=byId(id)||{},c=meta[id]||{};
    const st=!generic&&c.status?STATUS[c.status]:null;
    return `<span class="tool ${m.selected?'on':''}" title="${esc((generic?m.role||'':c.gives||'')||'')}">${icon(toolGlyph(m.tool||c.tool||''),'tg')}<b>${esc(m.name||c.name||id)}</b>${(m.tool||c.tool)?`<i>${esc(String(m.tool||c.tool).split(' ')[0])}</i>`:''}${st?`<em>${st}</em>`:''}</span>`}).join('');
  const links=(sc.links||[]).filter(id=>(P.chain||[]).some(c=>c.id===id));
  const linkChips=links.map(id=>{const c=(P.chain||[]).find(x=>x.id===id);
    return `<button class="chip slink" type="button" data-slink="${esc(id)}">${icon(linkIcon(id,c.name),'lg2')}${esc(c.name)}</button>`}).join('');
  const procs=(sc.processes||[]).map(p=>`<div class="sproc" title="${esc(p.what||'')}">${icon(p.icon||'chart')}
    <div><b>${esc(p.name)}</b>${p.formula?`<span class="f">${fmtFormula(p.formula)}</span>`:''}${p.what?`<span class="swhat">${esc(p.what)}</span>`:''}</div></div>`).join('');
  const ruler=[sc.size,sc.time].filter(Boolean).join(' · ')||M.ruler;
  return `<div class="scard" style="--sc:${M.col};width:${100-4*i}%" data-scale="${sc.id}">
   <div class="shead">${icon(M.icon,'lg')}<div class="sti"><b>${esc(sc.title||M.title)}</b>
     <span class="sruler">${icon('ruler','lg2')}${esc(ruler)}</span></div><span class="stag">${M.name}</span></div>
   <p class="ssum">${esc(sc.summary||M.summary)}</p>
   ${procs?`<div class="sprocs">${procs}</div>`:''}
   ${vizBox(s,P,sc)}
   ${meth?`<div class="smeth"><span class="lbl" style="margin:0">methods here</span>${meth}</div>`
    :`<p class="sassumed">${esc(M.assumed)}</p>`}
   ${linkChips?`<div class="slks"><span class="lbl" style="margin:0">chain links</span>${linkChips}</div>`:''}
  </div>`}

function scalesView(s,P){
  const scales=scalesOf(s,P),n=scales.length;
  const cards=scales.map((sc,i)=>{
    const card=scaleCard(s,P,sc,i,n);
    if(i===n-1)return card;
    const txt=sc.passes_down?`<span class="sptxt">${esc(sc.passes_down)}</span>`:'';
    return card+`<div class="spass"><span class="sparr">${icon('down')}</span>${txt}</div>`}).join('');
  const zoom=scales.map(sc=>`<span class="zladder" style="--sc:${SCALE_META[sc.id].col}">${icon(SCALE_META[sc.id].icon)}${SCALE_META[sc.id].ruler}</span>`).join('<i class="zjoin"></i>');
  return `<div class="scales">
   <div class="scales-head"><h4 class="chh" style="margin:0">From the reactor down to atoms</h4>
    <div class="zoom">${zoom}</div></div>
   <div class="szoom">${cards}</div>
   ${dataLayer(P)}
  </div>`}

/* data methods are not a scale: a small learning-layer footer */
function dataLayer(P){
  const meta=Object.fromEntries((AG.meta.methods||[]).map(m=>[m.id,m]));
  const ms=(P.methods||[]).filter(m=>methodClass(m,meta[m.id])==='data');
  if(!ms.length)return '';
  return `<div class="slayer">${icon('chart','lg2')}<b>Learning layer</b>
   ${ms.map(m=>`<span class="tool ${m.selected?'on':''}">${icon(toolGlyph(m.tool||meta[m.id]?.tool||''),'tg')}<b>${esc(m.name||meta[m.id]?.name||m.id)}</b></span>`).join('')}
   <span class="help" style="margin:0">fits, surrogates and the optimiser sit on top of the three scales, not inside one</span></div>`}

/* full-screen viewer for a visual */
function lightbox(s,P,scale){
  const z=scalesOf(s,P).find(x=>x.id===scale)||{id:scale,links:[]};
  const items=vizFor(s,P,z);const it=items[AG.vtab[scale]||0]||items[0];
  if(!it)return;const src='/viz/'+it.file,vid=isVid(it.file);
  const srctxt=typeof it.source==='string'?it.source
    :it.source&&typeof it.source==='object'?[it.source.script,it.source.run].filter(Boolean).join(' · '):'';
  const el=document.createElement('div');el.className='lb';
  el.innerHTML=`<div class="lb-in"><button class="lb-x btn ghost small" type="button" aria-label="close">${icon('close')}</button>
   <div class="lb-media">${vid?`<video src="${esc(src)}"${it.poster?` poster="${esc('/viz/'+it.poster)}"`:''} controls autoplay muted loop playsinline></video>`:`<img src="${esc(src)}" alt="">`}</div>
   <p class="lb-cap"><span class="pill ${it.kind==='model-input'?'web':'blind'}">${it.kind==='model-input'?'model input':'simulated result'}</span> <b>${esc(it.title||'')}</b> ${esc(it.caption||'')} ${srctxt?`<span class="meta">${esc(srctxt)}</span>`:''}</p></div>`;
  document.body.appendChild(el);document.body.style.overflow='hidden';
  const close=()=>{el.remove();document.body.style.overflow=''};
  el.onclick=e=>{if(e.target===el||e.target.classList.contains('lb-in'))close()};
  el.querySelector('.lb-x').onclick=close;
  el.querySelector('.lb-x').focus();
  el.onkeydown=e=>{if(e.key==='Escape'||e.key===' '){e.preventDefault();close()}};
  document.addEventListener('keydown',function esc2(e){if(e.key==='Escape')close();document.removeEventListener('keydown',esc2)})}

/* the chain the stack implements: knobs -> links -> targets, each link with the methods that serve it */
const SENS={high:'hi',medium:'md',low:'lo'};
function chainView(s,P,names){const ch=P.chain||[];if(!ch.length)return '';const ms=P.methods||[];
  const mby=Object.fromEntries(ms.map(m=>[m.id,m]));
  const meta=Object.fromEntries((AG.meta.methods||[]).map(m=>[m.id,m]));
  const scOf=id=>{const x=(scalesOf(s,P).find(z=>z.links.includes(id))||{}).id;return x?SCALE_META[x].col:null};
  const cards=ch.map((c,i)=>{const used=(c.methods||[]).concat(ms.filter(m=>m.link===c.id&&!(c.methods||[]).includes(m.id)).map(m=>m.id));
    const meth=used.map(id=>{const m=mby[id];const nm=names[id]||m?.name||id;
      return `<li class="${m?.selected?'on':''}">${esc(nm)}${m?.scale||meta[id]?.scale?` <span class="sc">${esc(m?.scale||meta[id].scale)}</span>`:''}</li>`}).join('');
    const col=scOf(c.id);
    return `<div class="clink" id="cl-${esc(c.id)}" style="--sc:${col||'transparent'}"><div class="ch">${icon(linkIcon(c.id,c.name),'li')}<span class="n">${i+1}</span><b>${esc(c.name)}</b><span class="sens ${SENS[c.sensitivity]||''}" title="${esc(c.why)}">${esc(c.sensitivity)}</span></div>
     <div class="io">${esc((c.inputs||[]).join(', '))} <span>→</span> ${esc((c.outputs||[]).join(', '))}</div>
     <div class="ph">${esc(c.physics)}</div>
     ${meth?`<ul class="cm">${meth}</ul>`:'<div class="gap">no method serves this link</div>'}
     <details><summary>why, data, alternatives, lessons</summary><p><b>Sensitivity:</b> ${esc(c.why)}</p><p><b>Data:</b> ${esc(c.data)}</p>
      ${(c.competing||[]).length?`<p><b>Competing mechanisms</b> (the benchmark decides):</p><ul>${c.competing.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}
      ${(c.lessons||[]).length?`<p><b>Lessons from similar simulation studies:</b></p><ul>${c.lessons.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}</details></div>`}).join('');
  return `<h4 class="chh" style="margin-top:22px">The chain: how the knobs reach the targets</h4><p class="help" style="margin:0 0 10px">Each link is one step of the synthesis with its inputs and outputs; the left edge marks its scale. Ticked methods (highlighted) supply that link's parameters; sensitivity says where the effort goes.</p><div class="chain">${cards}</div><h4 class="chh">Methods</h4>`}
function pStackOther(s,P,live){const ms=P.methods;const E=P.estimate||{};const sel=ms.filter(m=>m.selected);
  const rows=ms.map(m=>`<tr class="${m.selected?'sel':''}"><td><input type="checkbox" data-m="${esc(m.id)}" ${m.selected?'checked':''} ${live?'':'disabled'}></td>
    <td><div class="nm">${esc(m.name)}</div><div class="help" style="margin:2px 0 0">${m.scale?esc(m.scale)+' · ':''}tool: ${esc(m.tool)}</div></td>
    <td><div class="ins">${esc(m.insight)}</div><div class="help" style="margin:3px 0 0">computes: ${esc(m.role)} · feeds: ${esc(m.feeds)}${m.check?' · gate: '+esc(m.check):''}</div></td><td class="est">${dur(60*(+m.est_min||0))}</td></tr>`).join('');
  return `<div class="apanel"><h3>Simulation stack</h3><p class="sub">${esc(s.problem.material)} has no built-in simulator, so the agent designed this stack from the tools on this machine. After you pick the benchmark sample, a builder agent runs the ticked methods and assembles them into a predictor, then the predictor is tested blind on the held-out studies.</p>${scalesView(s,P)}${chainView(s,P,{})}
   <div style="overflow-x:auto"><table class="mtab"><thead><tr><th></th><th>method</th><th>insight for your goal</th><th>time</th></tr></thead><tbody>${rows}</tbody></table></div>
   <div class="tot"><span>build time (estimate)<br><b>${dur(E.now_s||0)}</b></span><span>selected<br><b>${sel.length} of ${ms.length}</b></span></div></div>`}
function pStack(s,P,live){const ms=P.methods||[];if(!ms.length)return wait(s.busy||'Choosing the stack.');
  if(ms[0].tool!==undefined)return pStackOther(s,P,live);
  const by=Object.fromEntries((AG.meta.methods||[]).map(m=>[m.id,m]));const mat=s.problem.material;
  const sel=ms.filter(m=>m.selected).map(m=>m.id);const E=P.estimate||{};
  const rows=STATUS_ORDER.map(stt=>{const grp=ms.filter(m=>by[m.id]?.status===stt);if(!grp.length)return '';
    return `<tr class="grp"><td colspan="4">${esc(STATUS_WORD[stt])}</td></tr>`+grp.map(m=>{const c=by[m.id];const ok=c.materials==='any'||c.materials.includes(mat);
      return `<tr class="${ok?'':'na'} ${m.selected?'sel':''}"><td><input type="checkbox" data-m="${m.id}" ${m.selected?'checked':''} ${ok&&live?'':'disabled'}></td>
       <td><div class="nm">${esc(c.name)}</div><div class="help" style="margin:2px 0 0">${esc(c.scale)}</div></td>
       <td><div class="ins">${esc(m.insight||c.insight)}</div><div class="help" style="margin:3px 0 0">gives: ${esc(c.gives)}${ok?'':' · '+esc(m.why)}</div></td><td class="est">${esc(c.est)}</td></tr>`}).join('')}).join('');
  return `<div class="apanel"><h3>Simulation stack</h3><p class="sub">Every method the platform knows, from reactor scale down to atoms. Ticked ones run in this study; tick or untick here or ask the agent.</p>${scalesView(s,P)}${chainView(s,P,Object.fromEntries(Object.entries(by).map(([k,v])=>[k,v.name])))}
   <div style="overflow-x:auto"><table class="mtab"><thead><tr><th></th><th>method</th><th>insight for your goal</th><th>time</th></tr></thead><tbody>${rows}</tbody></table></div>
   <div class="tot"><span>runs now<br><b>${dur(E.now_s||0)}</b></span><span>queued on the GPU pool<br><b>${E.queued?.length?dur(E.queued_s)+' · '+E.queued.length+' job(s)':'none'}</b></span><span>not built<br><b>${E.planned?.length?E.planned.join(', '):'none'}</b></span><span>selected<br><b>${sel.length}</b></span></div>
   ${E.queued?.length?'<div class="callout warn" style="margin-top:12px">Queued methods are recorded as job requests; the study continues with what runs now and does not wait for them.</div>':''}</div>`}
STEP_PANELS.stack = pStack;
