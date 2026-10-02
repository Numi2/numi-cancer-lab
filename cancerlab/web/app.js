import {LesionScene} from './scene.js';
const $=id=>document.getElementById(id);
const state={snapshot:null,run:null,evaluation:null,index:0,truth:false,loading:false,dirty:false};
const names={no_change:'No change',linear:'Linear growth',exponential:'Exponential growth'};
const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=n=>n===null||n===undefined?'Unknown':Number(n).toLocaleString(undefined,{maximumFractionDigits:2});
let scene;
try{scene=new LesionScene($('scene'));}catch{$('scene-fallback').hidden=false;}
async function api(path,body){
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Cancerlab-Request':'local-research'},body:JSON.stringify(body)});
  const result=await response.json();
  if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:JSON.stringify(result.detail));
  return result;
}
async function action(fn){
  state.loading=true;$('error').hidden=true;controls();
  try{await fn();}catch(error){$('error').textContent=error.message;$('error').hidden=false;}
  finally{state.loading=false;controls();}
}
function controls(){
  $('seal').disabled=state.loading||state.dirty||!state.snapshot?.studies.length||!$('organ').value;
  $('reveal').disabled=state.loading||!state.run||Boolean(state.evaluation)||state.dirty;
  $('apply').disabled=state.loading;$('patient').disabled=state.loading;
  $('truth-view').disabled=!state.evaluation;$('export').hidden=!state.run;
}
function invalidate(){state.run=null;state.evaluation=null;state.truth=false;state.dirty=true;render();}
async function load(){
  if(!$('cutoff').reportValidity()||!$('horizon').reportValidity())return;
  state.snapshot=null;state.run=null;state.evaluation=null;state.truth=false;state.dirty=true;render();
  const p=$('patient').value,cutoff=Number($('cutoff').value);
  state.snapshot=await api(`/api/patients/${encodeURIComponent(p)}/snapshot?cutoff_day=${cutoff}`);
  state.index=Math.max(0,state.snapshot.studies.length-1);state.dirty=false;
  const organs=[...new Set(state.snapshot.studies.flatMap(s=>s.coverage))];
  const previous=$('organ').value;
  $('organ').replaceChildren(...organs.map(o=>new Option(o.replaceAll('_',' '),o)));
  if(organs.includes(previous))$('organ').value=previous;
  render();
}
function study(){return state.truth?state.evaluation?.truth_study:state.snapshot?.studies[state.index];}
function burden(s){
  if(!s||s.annotation_scope!=='complete'||!s.coverage.includes($('organ').value))return null;
  const lesions=s.lesions.filter(m=>m.organ===$('organ').value);
  if(lesions.some(m=>m.state==='not_assessed'))return null;
  return lesions.reduce((v,m)=>v+m.volume_ml,0);
}
function render(){
  const history=state.snapshot,s=study(),organ=$('organ').value,method=$('method').value;
  $('dataset-badge').textContent=history?(history.synthetic?'SYNTHETIC DEMONSTRATION':'LOCAL RESEARCH DATA'):'NO OBSERVATIONS LOADED';
  $('footer-source').textContent=history?.synthetic?'Demonstration data are entirely synthetic.':'Local data remain subject to their original permissions and license.';
  $('metric-studies').textContent=history?.studies.length??'—';
  $('metric-window').textContent=history?`Information available by day ${history.cutoff_day}`:'At the selected cutoff';
  const lesions=s?.lesions.filter(m=>m.organ===organ)??[];
  $('metric-lesions').textContent=lesions.filter(m=>m.state!=='not_assessed').length;
  $('metric-volume').textContent=burden(s)===null?'Unknown':`${fmt(burden(s))} mL`;
  $('metric-scope').textContent=s?`${s.annotation_scope} annotation · ${organ||'no organ selected'}`:'Coverage not established';
  $('metric-state').textContent=state.evaluation?'Evaluated':state.run?'Sealed':state.dirty?'Reload required':'Draft';
  $('metric-state-note').textContent=state.evaluation?'Forecast scored against follow-up':state.run?'Prediction saved before reveal':'Follow-up not requested';
  $('step-observe').classList.toggle('active',Boolean(history));$('step-seal').classList.toggle('active',Boolean(state.run));$('step-reveal').classList.toggle('active',Boolean(state.evaluation));
  $('scene-day').textContent=s?`${state.truth?'Revealed follow-up':'Observation'} · day ${s.acquired_day}`:'No observed geometry';
  $('lesion-date').textContent=s?`Examination day ${s.acquired_day}`:'';
  $('study-tabs').replaceChildren(...(history?.studies??[]).map((v,i)=>{const b=document.createElement('button');b.textContent=`Day ${v.acquired_day}`;b.className=!state.truth&&state.index===i?'selected':'';b.onclick=()=>{state.index=i;state.truth=false;render();};return b;}));
  const items=lesions.map(m=>({id:m.lesion_id,center:m.centroid_ras_mm,volume:m.volume_ml,wire:false}));
  if(state.run){
    const prior=state.run.artifact.snapshot.studies.filter(v=>v.coverage.includes(organ)).at(-1);
    for(const [id,volume] of Object.entries(state.run.artifact.models[method].lesions_ml)){
      const m=prior?.lesions.find(m=>m.lesion_id===id);if(m)items.push({id,center:m.centroid_ras_mm,volume,wire:true});
    }
  }
  scene?.set(items);
  $('lesions').innerHTML=lesions.length?lesions.map(m=>`<tr><td><button data-lesion="${esc(m.lesion_id)}">${esc(m.lesion_id)}</button></td><td>${esc(m.organ.replaceAll('_',' '))}</td><td>${m.volume_ml===null?'Not assessed':`${fmt(m.volume_ml)} mL`}</td><td>${esc(m.correspondence)}</td><td><code title="${esc(m.evidence.sha256)}">${esc(m.evidence.method)} · ${esc(m.evidence.sha256.slice(0,10))}</code></td></tr>`).join(''):'<tr><td colspan="5">No assessed lesions in this view. This does not establish absence of disease.</td></tr>';
  for(const b of $('lesions').querySelectorAll('button'))b.onclick=()=>scene?.set(items,b.dataset.lesion);
  $('events').innerHTML=(history?.events??[]).map(e=>`<div class="event"><span>${esc(e.kind.toUpperCase())} · occurred day ${e.occurred_day} · available day ${e.available_day}</span><p>${esc(e.text)}</p></div>`).join('');
  $('input-evidence').textContent=history?JSON.stringify(history,null,2):'No snapshot loaded.';
  $('result-details').hidden=!state.evaluation;
  $('evaluation-evidence').textContent=state.evaluation?JSON.stringify(state.evaluation,null,2):'';
  $('forecast-label').textContent=state.run?`${names[method]} · target day ${state.run.artifact.target_day}`:'Observed only';
  $('run-status').textContent=state.run?`Sealed ${state.run.id.slice(0,10)} · input SHA-256 ${state.run.artifact.snapshot_sha256.slice(0,12)}`:'A forecast must be saved before the later observation is requested.';
  if(state.run)$('export').href=`/api/experiments/${state.run.id}/export`;
  $('scores').innerHTML=state.evaluation?Object.entries(state.evaluation.scores).map(([m,v])=>`<div class="score"><span>${names[m]} · organ-total error</span><strong>${v.total_absolute_error_ml===null?'Not scorable':fmt(v.total_absolute_error_ml)}</strong>${v.total_absolute_error_ml===null?'':'<em>mL absolute error</em>'}</div>`).join(''):'';
  const abstentions=state.run?Object.entries(state.run.artifact.models[method].abstentions).map(([id,why])=>`${id}: ${why}`).join('; '):'';
  $('comparison-note').textContent=state.evaluation?`${state.evaluation.interpretation}. ${state.evaluation.new_observed_tracks.length} newly observed track(s) included in complete organ-total scoring. Target offset: ${state.evaluation.horizon_offset_days} days.`:abstentions||'A missing or partially annotated examination is not interpreted as zero tumor burden.';
  controls();drawChart();
}
function drawChart(){
  const c=$('trajectory'),ctx=c.getContext('2d'),dpr=Math.min(devicePixelRatio||1,2);c.width=c.clientWidth*dpr;c.height=c.clientHeight*dpr;ctx.scale(dpr,dpr);
  const w=c.clientWidth,h=c.clientHeight,p={left:52,right:28,top:25,bottom:35};ctx.clearRect(0,0,w,h);
  const studies=state.snapshot?.studies??[],observed=studies.map(s=>[s.acquired_day,burden(s)]),method=$('method').value;
  const prediction=state.run?[state.run.artifact.target_day,state.run.artifact.models[method].total_ml]:null;
  const actual=state.evaluation?[state.evaluation.actual_day,state.evaluation.scores[method].actual_total_ml]:null;
  const all=[...observed,...(prediction?[prediction]:[]),...(actual?[actual]:[])];
  const xs=all.map(d=>d[0]),ys=all.map(d=>d[1]).filter(v=>v!==null);
  const xmin=Math.min(0,...xs),xmax=Math.max(90,...xs),ymax=Math.max(1,...ys)*1.2;
  const x=v=>p.left+(v-xmin)/(xmax-xmin)*(w-p.left-p.right),y=v=>h-p.bottom-v/ymax*(h-p.top-p.bottom);
  ctx.font='10px system-ui';ctx.lineWidth=1;
  for(let i=0;i<4;i++){const v=ymax*i/3;ctx.strokeStyle='#23333b';ctx.beginPath();ctx.moveTo(p.left,y(v));ctx.lineTo(w-p.right,y(v));ctx.stroke();ctx.fillStyle='#8497a3';ctx.fillText(fmt(v),12,y(v)+3);}
  ctx.fillStyle='#8497a3';ctx.fillText('mL',12,15);
  for(const d of [...new Set(xs)])ctx.fillText(`Day ${d}`,Math.min(w-65,Math.max(p.left-10,x(d)-20)),h-10);
  function line(points,color,dash=[]){ctx.strokeStyle=color;ctx.fillStyle=color;ctx.setLineDash(dash);ctx.lineWidth=2;ctx.beginPath();let pen=false;for(const [a,b] of points){if(b===null){pen=false;continue;}if(pen)ctx.lineTo(x(a),y(b));else ctx.moveTo(x(a),y(b));pen=true;}ctx.stroke();ctx.setLineDash([]);for(const [a,b] of points){if(b===null)continue;ctx.beginPath();ctx.arc(x(a),y(b),4,0,Math.PI*2);ctx.fill();}}
  line(observed,'#62d8bd');if(prediction&&observed.length)line([observed.at(-1),prediction],'#e6bc73',[5,5]);
  if(actual&&actual[1]!==null){ctx.strokeStyle='#e8eff2';ctx.lineWidth=2;ctx.beginPath();ctx.rect(x(actual[0])-5,y(actual[1])-5,10,10);ctx.stroke();ctx.fillStyle='#e8eff2';ctx.fillText('Revealed',Math.max(55,x(actual[0])-62),y(actual[1])-13);}
  if(!ys.length){ctx.fillStyle='#8497a3';ctx.fillText('No complete organ-burden measurements available.',p.left+15,80);}
}
$('settings').onsubmit=e=>{e.preventDefault();action(load);};
$('patient').onchange=()=>action(load);
for(const id of ['cutoff','horizon'])$(id).addEventListener('input',invalidate);
$('organ').onchange=()=>{state.run=null;state.evaluation=null;state.truth=false;render();};
$('method').onchange=render;$('truth-view').onclick=()=>{state.truth=true;render();};
$('seal').onclick=()=>action(async()=>{if(!$('settings').reportValidity())return;state.evaluation=null;state.truth=false;state.run=await api('/api/experiments',{patient_id:$('patient').value,spec:{cutoff_day:Number($('cutoff').value),horizon_days:Number($('horizon').value),organ:$('organ').value}});render();});
$('reveal').onclick=()=>action(async()=>{const result=await api(`/api/experiments/${state.run.id}/reveal`,{});state.evaluation=result.evaluation;render();});
new ResizeObserver(drawChart).observe($('trajectory'));
action(async()=>{const patients=await api('/api/patients');$('patient').replaceChildren(...patients.map(p=>new Option(p.patient_id,p.patient_id)));if(!patients.length)throw new Error('No patient records are configured.');await load();});
