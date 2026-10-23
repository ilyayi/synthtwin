/* The overview page (#/overview): the loop in one picture, what runs today,
   and what compute adds. Numbers are the recorded studies'; nothing is live-computed. */
const PITCH={
  loop:[
    ['target','Goal','a measurable target, agreed with you'],
    ['books','Literature','what was tried, what came out'],
    ['layers','Simulation stack','reactor → particle → atoms, built by an agent'],
    ['balance','Blind benchmark','must predict held-out published results'],
    ['spread','Your case','maps, sensitivities, best region'],
    ['flasklist','Recipe','conditions, checks, predicted bands'],
    ['robot','Self-driving lab','runs the protocol package'],
    ['chart','Measurements','compared with the prediction'],
  ],
};
function pitchPage(){
  const n=PITCH.loop.length,R=200,cx=260,cy=250;
  const pos=PITCH.loop.map((_,i)=>{const a=-Math.PI/2+i*2*Math.PI/n;return [cx+R*Math.cos(a),cy+R*Math.sin(a)]});
  const arcs=pos.map((p,i)=>{const q=pos[(i+1)%n];return `<path class="pt-arc${i===n-1?' back':''}" d="M${p[0]},${p[1]} A${R},${R} 0 0 1 ${q[0]},${q[1]}"/>`}).join('');
  const nodes=PITCH.loop.map(([ic,nm,sub],i)=>{const [x,y]=pos[i];
    return `<div class="pt-node ${i>=6?'lab':''}" style="left:${x/520*100}%;top:${y/500*100}%">${icon(ic,'lg')}<b>${nm}</b><span>${sub}</span></div>`}).join('');
  $('#app').innerHTML=`<div class="wrap pt">
   <p class="eyebrow" style="margin-top:28px">SynthTwin · overview</p>
   <h2>Self-driving labs can run any recipe.<br><em>Which recipe</em> is the bottleneck.</h2>
   <p class="lede">Robotic labs now build and run syntheses on their own. Deciding what to make still takes a PhD student months of reading and trial and error. SynthTwin is the agent that decides: it designs a simulation for the material, tests it on published results, and sends the robot a recipe that was tried in silico first.</p>
   <div class="pt-grid">
    <div class="pt-loop"><svg viewBox="0 0 520 500" aria-hidden="true"><defs><marker id="pta" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0L10,5L0,10z" fill="currentColor"/></marker></defs>${arcs}</svg>${nodes}
     <div class="pt-hub"><b>every run</b><span>calibrates the simulator<br>and teaches the agent</span></div></div>
    <div class="pt-side">
     <div class="pt-cols">
      <div><h4>Today</h4><ul>
       <li>One study at a time, a researcher confirms each step</li>
       <li>A frontier model plans; a cheaper model can execute</li>
       <li>Light simulation stacks run in minutes</li>
       <li>The robot package goes to a self-building lab</li></ul></div>
      <div class="more"><h4>With compute</h4><ul>
       <li>An auto-screener starts studies on its own, many in parallel</li>
       <li>Local models on our GPUs: no per-token cost</li>
       <li>Full stacks: MD and DFT where they change the decision (a quantum-dot stack is ~47 compute-hours)</li>
       <li>Every robot result calibrates the next study</li></ul></div>
     </div>
     <div class="pt-go"><a class="btn cu" href="#/s/aqueous-cds-quantum-dots-made-in-a-9-1022-010520/stack">See a quantum-dot study</a>
      <a class="btn ghost" href="#/optimizer">Choosing rule</a><a class="btn ghost" href="#/harness">Self-improvement</a></div>
    </div></div></div>`;
}
