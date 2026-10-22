/* Shared helpers for every page and panel: DOM/fetch utilities, the icon set,
   the number formatter and the inline-SVG charts. Loaded first; the per-step
   panels (steps/<step>/panel.js, served concatenated as /static/steps.js) and
   the agent shell (agent.js) build on it. */
const $=(s,r=document)=>r.querySelector(s), esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const api=async(p,o)=>{const r=await fetch(p,o);const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j};
const post=(p,b)=>api(p,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)});
const fmt=v=>v==null||isNaN(v)?'—':Math.abs(v)>=1e5||Math.abs(v)<0.01&&v!==0?(+v).toExponential(2):(+v).toPrecision(3).replace(/(\.\d*?)0+$/,'$1').replace(/\.$/,'');

/* each step's panel registers itself here: STEP_PANELS[step id] = render fn */
const STEP_PANELS={};

/* ---------------------------------------------------------------- icons (inline SVG) */
const IC={
heat:'<path d="M12 3.4c1.7 2 3.1 3.6 4 5.3.9 1.6 1.2 3.1.8 4.8a5.3 5.3 0 0 1-9.6 0c-.4-1.7-.1-3.2.8-4.8.4-.8 1-1.6 1.7-2.5.1 1.2.5 2.1 1.2 2.8C10.7 7.2 11.3 5.3 12 3.4z"/>',
stir:'<rect x="4.5" y="10" width="15" height="4.6" rx="2.3" transform="rotate(-22 12 12.3)"/><path d="M2.6 9.4h2.3M2 12.1h2.9M2.6 14.8h2.3M19.1 9.4h2.3M19.1 14.8h2.3"/>',
dose:'<path d="M12 3.4c1.9 2.3 3.2 3.9 3.2 5.7a3.2 3.2 0 0 1-6.4 0c0-1.8 1.3-3.4 3.2-5.7z"/><path d="M4.5 19.6h15"/><path d="M6.7 16.9c.8-.8 1.6-.8 2.4 0M14.9 16.9c.8-.8 1.6-.8 2.4 0"/>',
evaporate:'<path d="M4 19.6h16"/><path d="M7.4 15.8c1-1-1-2 0-3s-1-2 0-3M12 15.8c1-1-1-2 0-3s-1-2 0-3M16.6 15.8c1-1-1-2 0-3s-1-2 0-3"/>',
flow:'<path d="M3.6 8.4v7.2M20.4 8.4v7.2"/><path d="M5.6 12h11"/><path d="M16.6 12 14 9.6M16.6 12 14 14.4"/>',
light:'<circle cx="12" cy="12" r="3.6"/><path d="M12 3.1v2.4M12 18.5v2.4M3.1 12h2.4M18.5 12h2.4M5.7 5.7l1.7 1.7M16.6 16.6l1.7 1.7M18.3 5.7l-1.7 1.7M7.4 16.6l-1.7 1.7"/>',
vessel:'<path d="M9.4 2.4h5.2M10.4 2.4v6.8M13.6 2.4v6.8"/><circle cx="12" cy="15.3" r="6.2"/><path d="M6.3 17.1h11.4"/>',
plate:'<rect x="3" y="7.4" width="18" height="9.2" rx="1.8"/><g fill="currentColor" stroke="none"><circle cx="6.4" cy="10.5" r=".9"/><circle cx="10.8" cy="10.5" r=".9"/><circle cx="15.2" cy="10.5" r=".9"/><circle cx="19.6" cy="10.5" r=".9"/><circle cx="6.4" cy="13.8" r=".9"/><circle cx="10.8" cy="13.8" r=".9"/><circle cx="15.2" cy="13.8" r=".9"/><circle cx="19.6" cy="13.8" r=".9"/></g>',
molecule:'<circle cx="7" cy="16.4" r="2.6"/><circle cx="17" cy="16.4" r="2.6"/><circle cx="12" cy="7.6" r="2.6"/><path d="M9.2 14.9l1.8-4.9M14.8 14.9 13 10M9.7 16.4h4.6"/>',
reaction:'<path d="M5 8.4h11.4M16.4 8.4l-2.5-2.3M16.4 8.4l-2.5 2.3"/><path d="M19 15.6H7.6M7.6 15.6l2.5-2.3M7.6 15.6l2.5 2.3"/>',
nucleus:'<circle cx="12" cy="12" r="3.2"/><path d="M12 4.4v2.3M12 17.3v2.3M4.4 12h2.3M17.3 12h2.3M6.6 6.6l1.6 1.6M15.8 15.8l1.6 1.6M17.4 6.6l-1.6 1.6M8.2 15.8l-1.6 1.6"/>',
growth:'<circle cx="12" cy="14.3" r="3.5"/><circle cx="12" cy="14.3" r="7.2" stroke-dasharray="1.6 2.7"/><path d="M12 9.6V4.6M12 4.6 9.9 6.7M12 4.6l2.1 2.1"/>',
collide:'<circle cx="5.7" cy="14.9" r="3.5"/><circle cx="18.3" cy="14.9" r="3.5"/><path d="M12 5.8l1 2.5 2.5 1-2.5 1-1 2.5-1-2.5-2.5-1 2.5-1z"/>',
charge:'<path d="M13.2 2.8 6.2 13.4h4.5L9.6 21.2l7.4-10.9h-4.6z"/>',
ligand:'<circle cx="12" cy="12" r="4.1"/><path d="M12 7.9V4.2M16 8l2.6-2.6M16.1 16.1l2.5 2.5M12 16.1v3.7M8 16.1l-2.5 2.5M8 8 5.4 5.4"/><g fill="currentColor" stroke="none"><circle cx="12" cy="3.2" r="1.1"/><circle cx="19.7" cy="4.3" r="1.1"/><circle cx="19.7" cy="19.7" r="1.1"/><circle cx="12" cy="20.8" r="1.1"/><circle cx="4.3" cy="19.7" r="1.1"/><circle cx="4.3" cy="4.3" r="1.1"/></g>',
crystal:'<path d="M12 3.2l7.6 4.4v8.8L12 20.8l-7.6-4.4V7.6z"/><path d="M4.4 7.6 12 12l7.6-4.4M12 12v8.8"/>',
atom:'<ellipse cx="12" cy="12" rx="8.6" ry="3.4" transform="rotate(28 12 12)"/><ellipse cx="12" cy="12" rx="8.6" ry="3.4" transform="rotate(-28 12 12)"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/>',
bond:'<circle cx="5.8" cy="12" r="2.9"/><circle cx="18.2" cy="12" r="2.9"/><path d="M9.1 10.8h5.8M9.1 13.2h5.8"/>',
electron:'<circle cx="12" cy="12" r="8.4"/><circle cx="17.1" cy="7.2" r="1.7" fill="currentColor" stroke="none"/><path d="M9.6 12h4.8"/>',
spectrum:'<path d="M4 4.4v15.2h16"/><path d="M6.2 16.4c2.6 0 2.9-9 5.6-9s3 9 5.6 9"/>',
chart:'<path d="M4 4.4v15.2h16"/><path d="M8.2 19.6v-5.2M12.7 19.6V9.8M17.2 19.6v-7.6"/>',
target:'<circle cx="12" cy="12" r="8.4"/><circle cx="12" cy="12" r="4.4"/><circle cx="12" cy="12" r="1.2" fill="currentColor" stroke="none"/>',
books:'<path d="M4 5.4h5.2a1.8 1.8 0 0 1 1.8 1.8v11.6a1.8 1.8 0 0 0-1.8-1.8H4z"/><path d="M20 5.4h-5.2a1.8 1.8 0 0 0-1.8 1.8v11.6a1.8 1.8 0 0 1 1.8-1.8H20z"/>',
layers:'<path d="M12 3.4l8.6 4.6L12 12.6 3.4 8z"/><path d="M3.4 12.4 12 17l8.6-4.6M3.4 16.4 12 21l8.6-4.6"/>',
checklist:'<path d="M9.6 6.2h11M9.6 12h11M9.6 17.8h11"/><path d="M3.2 6l1.3 1.3L7 4.6M3.2 11.8l1.3 1.3L7 10.4M3.2 17.6l1.3 1.3L7 16.2"/>',
balance:'<path d="M12 3.6v16.4M8.4 20.4h7.2M4.4 7h15.2M4.4 7l-2 4M4.4 7l2 4M2.2 11a2.9 2.9 0 0 0 5.8 0M19.6 7l-2 4M19.6 7l2 4M17.4 11a2.9 2.9 0 0 0 5.8 0"/>',
map:'<path d="M9 4.2 3.4 6v13.8L9 18l6 1.8 5.6-1.8V4.2L15 6z"/><path d="M9 4.2V18M15 6v13.8"/>',
flasklist:'<path d="M6.2 3.4h2.6M6.8 3.4v7M8.2 3.4v7"/><circle cx="7.5" cy="15" r="4.6"/><path d="M14.5 6.4h6.2M14.5 10.8h6.2M14.5 15.2h4.2"/>',
robot:'<path d="M4.4 20.6h9.2M8 20.6v-3.1"/><circle cx="7" cy="16.4" r="1.4"/><circle cx="11.6" cy="10.6" r="1.4"/><circle cx="17" cy="7" r="1.4"/><path d="M7.9 15.2 10.8 11.7M12.9 9.7l2.8-1.7M17 7l2.7-1.9M17 7l3 .8"/>',
check:'<path d="M4.5 12.6l4.6 4.6L19.5 6.8"/>',
ruler:'<path d="M3.6 14.6 14.6 3.6l5.8 5.8L9.4 20.4z"/><path d="M7.2 11l1.6 1.6M10.2 8l1.6 1.6M13.2 5l1.6 1.6"/>',
spread:'<path d="M4 19.4h16"/><path d="M4.6 18.6c1.8-6.8 3.8-10.2 7.4-10.2s5.6 3.4 7.4 10.2"/><path d="M12 8.4v-3M10.4 6.8 12 5.2l1.6 1.6"/>',
book:'<path d="M5.5 4.4H15a2 2 0 0 1 2 2v13.2H7.5a2 2 0 0 1-2-2z"/><path d="M8.2 4.4v14.8"/>',
doc:'<path d="M6.6 3.6h7l4.4 4.4v12.4H6.6z"/><path d="M13.6 3.6V8h4.4M9.2 12.2h5.6M9.2 15.2h5.6"/>',
shield:'<path d="M12 3.2l7 2.6v5.4c0 4.4-3 7.6-7 9.6-4-2-7-5.2-7-9.6V5.8z"/>',
code:'<path d="M8.6 7.2 4.2 12l4.4 4.8M15.4 7.2 19.8 12l-4.4 4.8"/>',
mesh:'<path d="M12 4.6 20 19H4z"/><path d="M12 4.6V19M4 19l12-7.2M8 11.8h12"/>',
ml:'<g fill="currentColor" stroke="none"><circle cx="12" cy="5" r="1.7"/><circle cx="5.4" cy="17.6" r="1.7"/><circle cx="18.6" cy="17.6" r="1.7"/></g><path d="M11 6.6 6.4 16M13 6.6l4.6 9.4M7.1 17.6h9.8"/>',
play:'<path d="M8.6 5.4 18.6 12l-10 6.6z"/>',
close:'<path d="M6 6l12 12M18 6 6 18"/>',
down:'<path d="M12 4.4v13.2M7 12.8l5 5 5-5"/>'};
const icon=(n,c='')=>`<svg class="ico ${c}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[n]||IC.chart}</svg>`;

/* ---------------------------------------------------------------- charts (SVG) */
function ticks(lo,hi,n=5){if(!(hi>lo)){hi=lo+1;lo=lo-1}const st=Math.pow(10,Math.floor(Math.log10((hi-lo)/n)));const err=(hi-lo)/n/st;
  const step=st*(err>=7.5?10:err>=3.5?5:err>=1.5?2:1);const out=[];for(let v=Math.ceil(lo/step)*step;v<=hi+1e-9;v+=step)out.push(+v.toPrecision(12));return out}
function logTicks(lo,hi){const out=[];for(let e=Math.floor(Math.log10(lo));e<=Math.ceil(Math.log10(hi));e++)for(const m of [1,2,5]){const v=m*10**e;if(v>=lo*0.999&&v<=hi*1.001)out.push(v)}return out.length>=2?out:[lo,hi]}
function lineChart(o){const W=o.w||360,H=o.h||220,m={l:o.mini?34:46,r:o.y2?44:12,t:10,b:o.mini?24:34};
  const all=o.series.flatMap(s=>s.pts).filter(Boolean);if(!all.length)return '<p class="help">no data</p>';
  let xs=all.map(p=>p[0]).concat(o.marks||[]);if(o.points)xs=xs.concat(o.points.map(p=>p[0]));
  let ys=all.flatMap(p=>[p[1],p[2],p[3]]).filter(v=>v!=null&&isFinite(v));if(o.points)ys=ys.concat(o.points.map(p=>p[1]));
  if(o.target){if(o.target.lo!=null)ys.push(o.target.lo);if(o.target.hi!=null)ys.push(o.target.hi)}
  let x0=Math.min(...xs),x1=Math.max(...xs),y0=Math.min(...ys),y1=Math.max(...ys);const pad=(y1-y0||Math.abs(y1)||1)*0.08;y0-=pad;y1+=pad;if(x1===x0){x0-=1;x1+=1}
  const lg=o.logx&&x0>0;const fx=lg?v=>m.l+(Math.log(v)-Math.log(x0))/(Math.log(x1)-Math.log(x0))*(W-m.l-m.r):v=>m.l+(v-x0)/(x1-x0)*(W-m.l-m.r);
  const fy=v=>H-m.b-(v-y0)/(y1-y0)*(H-m.t-m.b);
  let g='';const xt=lg?logTicks(x0,x1):ticks(x0,x1,o.mini?3:5),yt=ticks(y0,y1,o.mini?3:5);
  yt.forEach(v=>{g+=`<line x1="${m.l}" x2="${W-m.r}" y1="${fy(v)}" y2="${fy(v)}" stroke="rgba(255,255,255,.06)"/><text x="${m.l-5}" y="${fy(v)+3}" text-anchor="end">${fmt(v)}</text>`});
  xt.forEach(v=>{g+=`<text x="${fx(v)}" y="${H-m.b+13}" text-anchor="middle">${fmt(v)}</text>`});
  g+=`<line x1="${m.l}" x2="${W-m.r}" y1="${H-m.b}" y2="${H-m.b}" stroke="rgba(255,255,255,.2)"/>`;
  if(o.target){const lo=o.target.lo??y0,hi=o.target.hi??y1;
    if(Math.abs(hi-lo)<1e-12)g+=`<line x1="${m.l}" x2="${W-m.r}" y1="${fy(lo)}" y2="${fy(lo)}" stroke="#62c6f2" stroke-dasharray="5 4"/>`;
    else g+=`<rect x="${m.l}" width="${W-m.l-m.r}" y="${fy(Math.min(hi,y1))}" height="${Math.max(0,fy(Math.max(lo,y0))-fy(Math.min(hi,y1)))}" fill="rgba(98,198,242,.1)"/>`}
  if(o.vline!=null&&o.vline>=x0&&o.vline<=x1)g+=`<line x1="${fx(o.vline)}" x2="${fx(o.vline)}" y1="${m.t}" y2="${H-m.b}" stroke="rgba(255,255,255,.25)" stroke-dasharray="3 3"/>`;
  if(o.anchor!=null)g+=`<path d="M${fx(o.anchor)},${H-m.b-6} l5,6 l-5,6 l-5,-6z" fill="#f2c14e" transform="translate(0,0)"/>`;
  o.series.forEach(s=>{const p=s.pts.filter(Boolean).sort((a,b)=>a[0]-b[0]);if(!p.length)return;
    if(s.band&&p.every(q=>q[2]!=null&&q[3]!=null)&&p.length>1)g+=`<path d="M${p.map(q=>`${fx(q[0])},${fy(q[3])}`).join('L')}L${p.slice().reverse().map(q=>`${fx(q[0])},${fy(q[2])}`).join('L')}Z" fill="${s.color}" opacity=".16"/>`;
    if(s.line!==false&&p.length>1)g+=`<path d="M${p.map(q=>`${fx(q[0])},${fy(q[1])}`).join('L')}" fill="none" stroke="${s.color}" stroke-width="${o.mini?1.5:2}" ${s.dash?'stroke-dasharray="5 4"':''}/>`;
    if(s.dots||p.length===1)p.forEach(q=>{g+=`<circle cx="${fx(q[0])}" cy="${fy(q[1])}" r="${o.mini?2.8:3.6}" fill="${s.color}"/>`})});
  (o.marks||[]).forEach(v=>{g+=`<line x1="${fx(v)}" x2="${fx(v)}" y1="${H-m.b}" y2="${H-m.b-6}" stroke="#8b8983" stroke-width="2"/>`});
  (o.points||[]).forEach(p=>{g+=`<circle cx="${fx(p[0])}" cy="${fy(p[1])}" r="4.5" fill="none" stroke="#f2f1ed" stroke-width="1.6"/>`});
  if(o.y2){const p=o.y2.pts.filter(q=>q[0]>=x0&&q[0]<=x1);const v2=p.map(q=>q[1]);const a=Math.min(...v2),b=Math.max(...v2)||1;const fy2=v=>H-m.b-(v-a)/((b-a)||1)*(H-m.t-m.b);
    g+=`<path d="M${p.map(q=>`${fx(q[0])},${fy2(q[1])}`).join('L')}" fill="none" stroke="${o.y2.color}" stroke-width="1.6" stroke-dasharray="4 3"/>`;
    ticks(a,b,4).forEach(v=>{g+=`<text x="${W-m.r+5}" y="${fy2(v)+3}" fill="${o.y2.color}">${fmt(v)}</text>`})}
  if(!o.mini){g+=`<text x="${(m.l+W-m.r)/2}" y="${H-3}" text-anchor="middle">${esc(o.xlab||'')}</text><text x="12" y="${(m.t+H-m.b)/2}" text-anchor="middle" transform="rotate(-90 12 ${(m.t+H-m.b)/2})">${esc(o.ylab||'')}</text>`}
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc((o.ylab||'')+' vs '+(o.xlab||''))}">${g}</svg>`}
function legend(ser){return `<div class="legend">${ser.map(s=>`<span><i style="background:${s.color}"></i>${esc(s.label)}</span>`).join('')}</div>`}
function barChart(o){const W=o.w,H=o.h,m={l:40,r:8,t:10,b:26};const gs=o.groups;if(!gs.length)return '<p class="help">not scored</p>';
  const mx=Math.max(...gs.map(x=>x.v))*1.1||1;const bw=(W-m.l-m.r)/gs.length;let g='';
  ticks(0,mx,4).forEach(v=>{const y=H-m.b-v/mx*(H-m.t-m.b);g+=`<line x1="${m.l}" x2="${W-m.r}" y1="${y}" y2="${y}" stroke="rgba(255,255,255,.06)"/><text x="${m.l-5}" y="${y+3}" text-anchor="end">${fmt(v)}</text>`});
  gs.forEach((x,i)=>{const h=x.v/mx*(H-m.t-m.b);g+=`<rect x="${m.l+i*bw+bw*.18}" y="${H-m.b-h}" width="${bw*.64}" height="${h}" rx="3" fill="${x.color}" opacity="${x.label==='null'?.55:.9}"/>
    <text x="${m.l+i*bw+bw/2}" y="${H-m.b+13}" text-anchor="middle">${esc(x.label)}</text><text x="${m.l+i*bw+bw/2}" y="${H-m.b-h-4}" text-anchor="middle" style="fill:var(--ink)">${fmt(x.v)}</text>`});
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`}
function tornado(rows,c,tb){const W=360,rh=30,m={l:150,r:16,t:8,b:24};const H=m.t+m.b+rows.length*rh;
  const vals=rows.flatMap(r=>[r.min,r.max]).concat(c!=null?[c]:[]).concat([tb?.lo,tb?.hi].filter(v=>v!=null));
  let lo=Math.min(...vals),hi=Math.max(...vals);const pd=(hi-lo||1)*.06;lo-=pd;hi+=pd;const fx=v=>m.l+(v-lo)/(hi-lo)*(W-m.l-m.r);let g='';
  ticks(lo,hi,4).forEach(v=>{g+=`<line x1="${fx(v)}" x2="${fx(v)}" y1="${m.t}" y2="${H-m.b}" stroke="rgba(255,255,255,.06)"/><text x="${fx(v)}" y="${H-m.b+14}" text-anchor="middle">${fmt(v)}</text>`});
  if(tb&&tb.lo!=null&&tb.hi!=null&&tb.hi>tb.lo)g+=`<rect x="${fx(tb.lo)}" y="${m.t}" width="${fx(tb.hi)-fx(tb.lo)}" height="${H-m.t-m.b}" fill="rgba(98,198,242,.1)"/>`;
  else if(tb&&(tb.lo??tb.hi)!=null)g+=`<line x1="${fx(tb.lo??tb.hi)}" x2="${fx(tb.lo??tb.hi)}" y1="${m.t}" y2="${H-m.b}" stroke="#62c6f2" stroke-dasharray="5 4"/>`;
  rows.forEach((r,i)=>{const y=m.t+i*rh+6;g+=`<text x="${m.l-8}" y="${y+12}" text-anchor="end" style="fill:var(--ink2)">${esc(r.knob)}</text>
    <rect x="${fx(r.min)}" y="${y}" width="${Math.max(2,fx(r.max)-fx(r.min))}" height="${rh-12}" rx="3" fill="#d8894f" opacity=".75"/>
    <circle cx="${fx(r.low)}" cy="${y+(rh-12)/2}" r="3.5" fill="#08090b" stroke="#f2f1ed"/><circle cx="${fx(r.high)}" cy="${y+(rh-12)/2}" r="3.5" fill="#f2f1ed"/>`});
  if(c!=null)g+=`<line x1="${fx(c)}" x2="${fx(c)}" y1="${m.t}" y2="${H-m.b}" stroke="#f2f1ed" stroke-width="1.2"/>`;
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg><div class="legend"><span>○ knob at low end</span><span>● at high end</span><span><i style="background:rgba(98,198,242,.5)"></i>target</span></div>`}
function viridis(t){const c=[[68,1,84],[59,82,139],[33,145,140],[94,201,98],[253,231,37]];t=Math.max(0,Math.min(1,t))*4;const i=Math.min(3,Math.floor(t)),f=t-i;
  return `rgb(${c[i].map((v,k)=>Math.round(v+(c[i+1][k]-v)*f)).join(',')})`}
function heatmap(h,pts){const W=360,H=300,m={l:46,r:56,t:8,b:34};const nx=h.x.length,ny=h.y.length;const v=h.z.flat().filter(x=>x!=null);if(!v.length)return '';
  const a=Math.min(...v),b=Math.max(...v);const cw=(W-m.l-m.r)/nx,chh=(H-m.t-m.b)/ny;let g='';
  const fx=x=>m.l+(x-h.x[0])/(h.x[nx-1]-h.x[0])*(W-m.l-m.r-cw)+cw/2,fy=y=>H-m.b-(y-h.y[0])/(h.y[ny-1]-h.y[0])*(H-m.t-m.b-chh)-chh/2;
  h.z.forEach((row,j)=>row.forEach((z,i)=>{if(z==null)return;g+=`<rect x="${m.l+i*cw}" y="${H-m.b-(j+1)*chh}" width="${cw+.5}" height="${chh+.5}" fill="${viridis((z-a)/((b-a)||1))}"><title>${esc(h.x_key)}=${fmt(h.x[i])}, ${esc(h.y_key)}=${fmt(h.y[j])}: ${fmt(z)}</title></rect>`}));
  const t=h.target||{};[t.value,t.min,t.max].filter(x=>x!=null).forEach(lv=>{g+=`<path d="${iso(h,lv,fx,fy)}" fill="none" stroke="#62c6f2" stroke-width="2.2"/>`});
  ticks(h.x[0],h.x[nx-1],4).forEach(x=>{g+=`<text x="${fx(x)}" y="${H-m.b+13}" text-anchor="middle">${fmt(x)}</text>`});
  ticks(h.y[0],h.y[ny-1],4).forEach(y=>{g+=`<text x="${m.l-5}" y="${fy(y)+3}" text-anchor="end">${fmt(y)}</text>`});
  (pts||[]).forEach(p=>{if(p[0]!=null&&p[1]!=null)g+=`<circle cx="${fx(p[0])}" cy="${fy(p[1])}" r="5" fill="none" stroke="#fff" stroke-width="2"><title>${esc(p[2])}</title></circle>`});
  for(let k=0;k<20;k++)g+=`<rect x="${W-m.r+14}" y="${m.t+(19-k)*(H-m.t-m.b)/20}" width="10" height="${(H-m.t-m.b)/20+.5}" fill="${viridis(k/19)}"/>`;
  g+=`<text x="${W-m.r+28}" y="${m.t+8}">${fmt(b)}</text><text x="${W-m.r+28}" y="${H-m.b}">${fmt(a)}</text>`;
  g+=`<text x="${(m.l+W-m.r)/2}" y="${H-3}" text-anchor="middle">${esc(h.x_key)}</text><text x="12" y="${(m.t+H-m.b)/2}" text-anchor="middle" transform="rotate(-90 12 ${(m.t+H-m.b)/2})">${esc(h.y_key)}</text>`;
  return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`}
function iso(h,lv,fx,fy){/* marching squares on the grid nodes, one level */let d='';const z=h.z,nx=h.x.length,ny=h.y.length;
  const P=(i,j,i2,j2)=>{const a=z[j][i],b=z[j2][i2];const t=(lv-a)/((b-a)||1e-12);return [fx(h.x[i]+(h.x[i2]-h.x[i])*t),fy(h.y[j]+(h.y[j2]-h.y[j])*t)]};
  for(let j=0;j<ny-1;j++)for(let i=0;i<nx-1;i++){const c=[z[j][i],z[j][i+1],z[j+1][i+1],z[j+1][i]];if(c.some(v=>v==null))continue;
    const e=[];const E=[[0,1,i,j,i+1,j],[1,2,i+1,j,i+1,j+1],[2,3,i+1,j+1,i,j+1],[3,0,i,j+1,i,j]];
    E.forEach(([p,q,a1,b1,a2,b2])=>{if((c[p]-lv)*(c[q]-lv)<0)e.push(P(a1,b1,a2,b2))});
    for(let k=0;k+1<e.length;k+=2)d+=`M${e[k][0]},${e[k][1]}L${e[k+1][0]},${e[k+1][1]}`}
  return d}
function hist(x,n){const W=360,H=190,m={l:12,r:10,t:10,b:30};const mx=Math.max(...n)||1;const pairs=x.map((d,i)=>[d,n[i]]).filter(p=>p[1]>mx*1e-3);if(!pairs.length)return '';
  const x0=pairs[0][0],x1=pairs[pairs.length-1][0];const span=(x1-x0)||1;const bw=(W-m.l-m.r)/pairs.length;let g='';
  pairs.forEach((p,i)=>{const h=p[1]/mx*(H-m.t-m.b);g+=`<rect x="${m.l+i*bw}" y="${H-m.b-h}" width="${Math.max(1,bw-1)}" height="${h}" fill="#d8894f" opacity=".85"/>`});
  ticks(x0,x1,5).forEach(v=>{g+=`<text x="${m.l+(v-x0)/span*(W-m.l-m.r)}" y="${H-m.b+13}" text-anchor="middle">${fmt(v)}</text>`});
  g+=`<text x="${W/2}" y="${H-3}" text-anchor="middle">core diameter (nm)</text>`;return `<svg viewBox="0 0 ${W} ${H}">${g}</svg>`}

