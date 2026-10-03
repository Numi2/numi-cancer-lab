import {LesionScene} from './scene.js';
import {ScanViewer} from './scanview.js';
import {ReviewWorkspace} from './review.js';
import {$,esc,fmt,title,names,request,cancel,notify,confirmAction,tabKeys} from './ui.js';
import {organBurden,drawTrajectory} from './chart.js';

const state={patients:[],patient_id:'',snapshot:null,protocol:{cutoff_day:90,horizon_days:90,tolerance_days:0,organ:''},run:null,evaluation:null,index:0,truth:false,dirty:false,loading:false,writePending:false,epoch:0,view:'overview',historyNext:null};
const scanViewer=new ScanViewer($('scan-host'));
const review=new ReviewWorkspace($('review-host'),()=>({patient_id:state.patient_id,cutoff_day:state.protocol.cutoff_day,ready:Boolean(state.snapshot)&&!state.dirty&&!state.loading}));
let scene,lastRead=null;
try{scene=new LesionScene($('scene'));}catch{$('scene-fallback').hidden=false;}
const selectedStudy=()=>state.truth?state.evaluation?.truth_study:state.snapshot?.studies[state.index];
const burden=s=>organBurden(s,state.protocol.organ);
const methodDescriptions={no_change:'Keeps the last verified lesion volume unchanged.',linear:'Continues the volume change measured between two verified observations.',exponential:'Continues proportional growth between two positive, verified measurements.'};

function errorMessage(error,heading='Request could not be completed',retry=null) {
  if(error.name==='AbortError')return;
  $('error-title').textContent=heading;$('error-message').textContent=error.message;$('error').hidden=false;
  $('retry').hidden=!retry;$('retry').onclick=retry;notify('Action needs attention. See the message above the workspace.');
}
function controls() {
  const ready=Boolean(state.snapshot?.studies.length)&&Boolean(state.protocol.organ)&&!state.dirty&&!state.loading;
  $('seal').disabled=!ready||state.writePending||Boolean(state.run);
  $('reveal').disabled=!state.run||Boolean(state.evaluation)||state.dirty||state.loading||state.writePending;
  $('seal').textContent=state.writePending==='seal'?'Saving forecast…':state.run?'Forecast sealed':'Seal forecast →';
  $('reveal').textContent=state.writePending==='reveal'?'Evaluating…':state.evaluation?'Follow-up evaluated':'Reveal follow-up & score';
  $('apply').disabled=Boolean(state.writePending)||Boolean(state.snapshot&&!state.dirty&&!state.loading);
  $('settings-fields').disabled=Boolean(state.writePending);$('patient').disabled=Boolean(state.writePending);$('patient-search').disabled=Boolean(state.writePending);
  $('method').disabled=Boolean(state.writePending);$('new-draft').disabled=Boolean(state.writePending);$('new-draft').hidden=!state.run;
  $('truth-view').disabled=!state.evaluation||state.writePending;$('truth-view').setAttribute('aria-pressed',String(state.truth));
  $('export').hidden=!state.run;$('dirty-note').hidden=!state.dirty;$('scope-loading').hidden=!state.loading;
  $('refresh-history').disabled=Boolean(state.writePending)||state.loading;
  $('quick-action').disabled=state.evaluation?false:state.run?$('reveal').disabled:$('seal').disabled;
  $('quick-action').textContent=state.evaluation?'View results ↓':state.run?'Reveal follow-up →':'Seal forecast →';
  $('quick-status').textContent=state.evaluation?'Evaluated':state.run?'Forecast saved':'Draft forecast';
}
function inputProtocol() {return {cutoff_day:Number($('cutoff').value),horizon_days:Number($('horizon').value),tolerance_days:Number($('tolerance').value),organ:$('organ').value};}
function syncInputs() {const p=state.protocol;$('cutoff').value=p.cutoff_day;$('horizon').value=p.horizon_days;$('tolerance').value=p.tolerance_days;$('organ').value=p.organ;state.dirty=false;controls();}
function updateOrgans(snapshot,preferred) {
  const organs=[...new Set((snapshot?.studies||[]).flatMap(s=>s.coverage))];
  $('organ').replaceChildren(...organs.map(o=>new Option(title(o),o)));$('organ').required=Boolean(organs.length);
  $('organ').value=organs.includes(preferred)?preferred:organs[0]||'';return $('organ').value;
}
function invalidate() {state.dirty=JSON.stringify(inputProtocol())!==JSON.stringify(state.protocol);controls();}
async function allowReviewReset() {return !review.isDirty()||await confirmAction('Discard the unsaved review?','Changing the patient or evidence cutoff clears these draft decisions. Export the review first to keep them.','Discard draft');}
async function loadScope(patientId=state.patient_id) {
  if(!$('cutoff').reportValidity()||!$('horizon').reportValidity()||!$('tolerance').reportValidity())return;
  if(!await allowReviewReset()){$('patient').value=state.patient_id;return;}
  const protocol=inputProtocol(),epoch=++state.epoch;
  state.patient_id=patientId;state.loading=true;state.snapshot=null;state.run=null;state.evaluation=null;state.truth=false;state.dirty=false;review.reset();scanViewer.select(null);
  $('lesion-dialog').close();$('error').hidden=true;render();
  lastRead=()=>loadScope(patientId);
  try {
    const data=await request(`/api/patients/${encodeURIComponent(patientId)}/snapshot?cutoff_day=${protocol.cutoff_day}`,{channel:'scope'});
    if(epoch!==state.epoch)return;
    state.snapshot=data;protocol.organ=updateOrgans(data,protocol.organ);state.protocol=protocol;state.index=Math.max(0,data.studies.length-1);syncInputs();
    $('lesion-search').value='';render();
    if(state.view==='history')loadHistory();
  } catch(error){if(epoch===state.epoch)errorMessage(error,'Could not load observations',lastRead);}
  finally{if(epoch===state.epoch){state.loading=false;render();}}
}
async function write(kind,fn) {
  if(state.writePending)return;
  state.writePending=kind;$('error').hidden=true;controls();
  try{await fn();}catch(error){errorMessage(error,kind==='reveal'?'Follow-up could not be evaluated':'Forecast could not be saved');}
  finally{state.writePending=false;render();}
}
function openView(view,focus=false) {
  state.view=view;document.body.dataset.view=view;$('toast').textContent='';
  for(const tab of $('workspace-tabs').querySelectorAll('[role=tab]')){const selected=tab.dataset.view===view;tab.setAttribute('aria-selected',String(selected));tab.tabIndex=selected?0:-1;$(`view-${tab.dataset.view}`).hidden=!selected;}
  if(focus)$(`view-${view}`).focus({preventScroll:true});
  if(view==='images')updateScan();else scanViewer.suspend();
  if(view==='history')loadHistory();
  if(view==='overview'){scene?.draw();drawTrajectory(state,$('method').value);}
}
function updateScan() {
  const s=selectedStudy();
  scanViewer.select(state.view==='images'&&state.snapshot&&s&&!state.loading?{patient_id:state.patient_id,study_id:s.study_id,cutoff_day:state.snapshot.cutoff_day,organ:state.protocol.organ,run_id:state.truth?state.run?.id:null}:null);
}
function render() {
  const history=state.snapshot,s=selectedStudy(),organ=state.protocol.organ,method=$('method').value,lesions=s?.lesions.filter(m=>m.organ===organ)||[];
  $('patient-title').textContent=state.patient_id;
  $('dataset-badge').textContent=history?(history.synthetic?'Synthetic demonstration':'Local research data'):state.loading?'Loading observations':'No observations loaded';
  $('footer-source').textContent=history?.synthetic?'Synthetic demonstrations are not patient observations.':'Original data permissions and licenses still apply.';
  $('scope-description').textContent=history?`Loaded evidence through day ${history.cutoff_day}. Changes above apply only when confirmed.`:'No patient observations loaded.';
  $('target-preview').textContent=history?`Target day ${state.protocol.cutoff_day+state.protocol.horizon_days} · tolerance ±${state.protocol.tolerance_days}`:'';
  $('metric-studies').textContent=history?.studies.length??'—';$('metric-window').textContent=history?`Available by day ${history.cutoff_day}`:'At the evidence cutoff';
  $('metric-lesions').textContent=s?lesions.filter(m=>m.state!=='not_assessed').length:'—';
  $('metric-lesion-note').textContent=s?`${title(organ)} · examination day ${s.acquired_day}`:'Selected organ and examination';
  $('metric-volume').textContent=burden(s)===null?'Unknown':`${fmt(burden(s))} mL`;
  $('metric-scope').textContent=s?`${title(s.annotation_scope)} annotation`:'Complete annotation required';
  const status=state.evaluation?'Evaluated':state.run?'Sealed':'Draft';$('metric-state').textContent=status;$('run-badge').textContent=status;
  $('run-badge').className=`badge ${state.run?'good':'subtle'}`;
  $('metric-state-note').textContent=state.evaluation?'Saved prediction compared with follow-up':state.run?'Saved before follow-up reveal':'Follow-up not requested';
  for(const [id,active] of [['step-observe',Boolean(history?.studies.length)],['step-seal',Boolean(state.run)],['step-reveal',Boolean(state.evaluation)]])$(id).classList.toggle('active',active);
  $('scene-day').textContent=s?`${state.truth?'Revealed follow-up':'Examination'} · day ${s.acquired_day}`:'No available examination';
  $('lesion-date').textContent=s?`Day ${s.acquired_day}`:'No examination';
  $('study-tabs').replaceChildren(...(history?.studies||[]).map((v,i)=>{const b=document.createElement('button');b.textContent=`Day ${v.acquired_day}`;b.className=!state.truth&&state.index===i?'selected':'';b.setAttribute('aria-pressed',String(!state.truth&&state.index===i));b.onclick=()=>{state.index=i;state.truth=false;render();};return b;}));
  const items=lesions.map(m=>({id:m.lesion_id,center:m.centroid_ras_mm,volume:m.volume_ml,wire:false}));
  const latest=state.run?.artifact.snapshot.studies.filter(v=>v.coverage.includes(organ)).at(-1);
  const showForecast=Boolean(state.run&&!state.truth&&s?.study_id===latest?.study_id);
  if(showForecast)for(const [id,volume] of Object.entries(state.run.artifact.models[method].lesions_ml)){const m=latest.lesions.find(m=>m.lesion_id===id);if(m)items.push({id,center:m.centroid_ras_mm,volume,wire:true});}
  // Never overlay positions from different unregistered examinations.
  scene?.set(items);$('scene-empty').hidden=items.some(m=>m.center&&m.volume>0)||!$('scene-fallback').hidden;
  $('forecast-legend').hidden=!showForecast;
  $('geometry-note').textContent=showForecast?'Forecast at last measured positions':state.truth?'Revealed measurements · own scan frame':'Measured volumes · independent scan frame';
  $('method-description').textContent=methodDescriptions[method];
  $('forecast-label').textContent=state.run?`${names[method]} · target day ${state.run.artifact.target_day}`:'Observed only';
  $('run-status').textContent=state.run?`Saved ${state.run.id.slice(0,10)} · input ${state.run.artifact.snapshot_sha256.slice(0,12)}`:!history?.studies.length?'No available examination. Try a later evidence cutoff.':'Save all three forecasts before requesting the later examination.';
  if(state.run)$('export').href=`/api/experiments/${encodeURIComponent(state.run.id)}/export`;
  $('scores').innerHTML=state.evaluation?['no_change','linear','exponential'].map(m=>{const v=state.evaluation.scores[m];return `<article class="score ${m===method?'current':''}"><span>${names[m]}</span><strong>${v.total_absolute_error_ml===null?'Not scorable':fmt(v.total_absolute_error_ml)}</strong><em>${v.total_absolute_error_ml===null?'Incomplete burden or prediction':'mL · absolute organ-total error'}</em></article>`;}).join(''):'';
  const abstentions=state.run?Object.entries(state.run.artifact.models[method].abstentions).map(([id,why])=>`${id}: ${why}`).join('; '):'';
  $('comparison-note').textContent=state.evaluation?`${state.evaluation.interpretation}. ${state.evaluation.new_observed_tracks.length} newly observed track(s) included in complete organ-total scoring. Follow-up offset: ${state.evaluation.horizon_offset_days} days.`:abstentions||'Missing or partially annotated examinations remain unknown, not zero. No calibrated confidence interval is available.';
  renderLesions();
  $('events').innerHTML=history?.events.length?history.events.map(e=>`<article class="event"><span>${esc(title(e.kind))} · occurred day ${e.occurred_day} · available day ${e.available_day}</span><p>${esc(e.text)}</p></article>`).join(''):'<p class="footnote">No clinical notes were available by this cutoff.</p>';
  $('input-evidence').textContent=history?JSON.stringify(history,null,2):'No snapshot loaded.';
  $('result-details').hidden=!state.evaluation;$('evaluation-evidence').textContent=state.evaluation?JSON.stringify(state.evaluation,null,2):'';
  if(state.view==='images')updateScan();
  controls();drawTrajectory(state,method);
}
function renderLesions() {
  const s=selectedStudy(),all=s?.lesions.filter(m=>m.organ===state.protocol.organ)||[],query=$('lesion-search').value.toLowerCase();
  const lesions=all.filter(m=>m.lesion_id.toLowerCase().includes(query));
  lesions.sort((a,b)=>$('lesion-sort').value==='volume'?(b.volume_ml??-1)-(a.volume_ml??-1):$('lesion-sort').value==='review'?Number(a.correspondence==='confirmed')-Number(b.correspondence==='confirmed')||a.lesion_id.localeCompare(b.lesion_id):a.lesion_id.localeCompare(b.lesion_id,undefined,{numeric:true}));
  $('lesion-count').textContent=`${lesions.length} of ${all.length} observations`;
  $('lesions').innerHTML=lesions.length?lesions.map(m=>`<tr><td><button data-lesion="${esc(m.lesion_id)}">${esc(m.lesion_id)}</button><small>${esc(title(m.organ))}</small></td><td>${m.volume_ml===null?'Not assessed':`${fmt(m.volume_ml)} mL`}</td><td><span class="identity ${m.correspondence==='confirmed'?'':'pending'}">${m.correspondence==='confirmed'?'Reviewed':'Unverified'}</span></td><td>${esc(title(m.evidence.method))}<code>${esc(m.evidence.sha256.slice(0,12))}</code></td><td><button class="row-link" data-lesion="${esc(m.lesion_id)}" aria-label="Inspect ${esc(m.lesion_id)} evidence">↗</button></td></tr>`).join(''):`<tr><td colspan="5"><div class="empty-state"><h3>${query?'No matching identifiers':'No lesions in this view'}</h3><p>${query?'Clear the search to see all observations.':'This does not establish absence of disease. Check organ coverage and the selected examination.'}</p></div></td></tr>`;
  for(const b of $('lesions').querySelectorAll('[data-lesion]'))b.onclick=()=>showLesion(b.dataset.lesion);
}
function showLesion(id) {
  const s=selectedStudy(),m=s?.lesions.find(m=>m.lesion_id===id);if(!m)return;
  $('lesion-title').textContent=`${id} · ${title(m.organ)}`;
  const prior=(state.snapshot?.studies||[]).flatMap(st=>st.lesions.filter(v=>v.lesion_id===id&&v.organ===m.organ).map(v=>({day:st.acquired_day,measurement:v})));
  $('lesion-detail').innerHTML=`<dl class="detail-grid"><div><dt>Measured volume</dt><dd>${m.volume_ml===null?'Not assessed':`${fmt(m.volume_ml)} mL`}</dd></div><div><dt>Examination</dt><dd>Day ${s.acquired_day}</dd></div><div><dt>Identity review</dt><dd>${m.correspondence==='confirmed'?'Reviewed':'Unverified'}</dd></div><div><dt>Measurement status</dt><dd>${esc(title(m.state))}</dd></div></dl><h3>Physical position · RAS millimetres</h3><p>${m.centroid_ras_mm?m.centroid_ras_mm.map(fmt).join(' · '):'No measured centroid is available.'}</p><h3>Source evidence</h3><p><code>${esc(m.evidence.source)}</code></p><p class="footnote">SHA-256<br><code>${esc(m.evidence.sha256)}</code></p><h3>Earlier records with this identifier</h3><div class="table-scroll"><table><thead><tr><th>Day</th><th>Volume</th><th>Identity</th></tr></thead><tbody>${prior.map(v=>`<tr><td>${v.day}</td><td>${fmt(v.measurement.volume_ml)} mL</td><td>${esc(v.measurement.correspondence)}</td></tr>`).join('')}</tbody></table></div><p class="footnote">A repeated unverified identifier is not proof of the same lesion. Positions from separate examinations require reviewed registration.</p><button id="detail-scan" class="secondary">Open this examination in CT viewer →</button>`;
  $('detail-scan').onclick=()=>{$('lesion-dialog').close();openView('images',true);};$('lesion-dialog').showModal();
}
async function loadHistory(append=false) {
  if(!state.snapshot)return;
  const epoch=state.epoch,p=state.patient_id,cutoff=state.protocol.cutoff_day,offset=append?state.historyNext:0;
  if(append&&offset===null)return;
  if(!append)$('history-list').innerHTML='<div class="empty-state"><p>Loading saved experiments…</p></div>';
  $('more-history').disabled=true;
  try {
    const data=await request(`/api/patients/${encodeURIComponent(p)}/experiments?cutoff_day=${cutoff}&offset=${offset}`,{channel:'history'});
    if(epoch!==state.epoch)return;
    const rows=data.items.map(v=>`<article class="history-row"><div><h3>${esc(title(v.spec.organ))} · day ${v.spec.cutoff_day} → ${v.spec.cutoff_day+v.spec.horizon_days}</h3><p>${esc(new Date(v.created_at).toLocaleString())} · <code>${esc(v.id.slice(0,10))}</code></p></div><div class="history-meta"><span class="badge ${v.state==='evaluated'?'good':'subtle'}">${esc(title(v.state))}</span><button class="secondary" data-resume="${esc(v.id)}">Resume →</button></div></article>`).join('');
    if(append)$('history-list').insertAdjacentHTML('beforeend',rows);else $('history-list').innerHTML=rows||'<div class="empty-state"><h3>No saved experiments here yet</h3><p>Seal a forecast in Overview. It will remain available here even after you change patients or close the browser.</p><button id="history-start" class="secondary">Go to Overview →</button></div>';
    $('history-start')?.addEventListener('click',()=>openView('overview',true));
    for(const b of $('history-list').querySelectorAll('[data-resume]'))b.onclick=()=>resume(b.dataset.resume);
    state.historyNext=data.next_offset;$('more-history').hidden=data.next_offset===null;
  }catch(error){if(epoch===state.epoch)errorMessage(error,'Could not load saved experiments',()=>loadHistory(append));}
  finally{$('more-history').disabled=false;}
}
async function resume(id) {
  if(state.writePending||!await allowReviewReset())return;
  const epoch=++state.epoch;state.loading=true;controls();
  try {
    const [run,saved]=await Promise.all([request(`/api/experiments/${encodeURIComponent(id)}`,{channel:'resume'}),request(`/api/experiments/${encodeURIComponent(id)}/evaluation`,{channel:'saved-result'})]);
    if(epoch!==state.epoch)return;
    if(run.artifact.patient_id!==state.patient_id)throw new Error('The saved experiment belongs to a different patient.');
    state.snapshot=run.artifact.snapshot;state.run=run;state.evaluation=saved.evaluation;state.protocol={cutoff_day:run.artifact.spec.cutoff_day,horizon_days:run.artifact.spec.horizon_days,tolerance_days:run.artifact.spec.tolerance_days,organ:run.artifact.spec.organ};
    state.index=Math.max(0,state.snapshot.studies.length-1);state.truth=false;updateOrgans(state.snapshot,state.protocol.organ);syncInputs();review.reset();render();openView('overview',true);notify('Saved experiment restored. No new forecast or reveal was requested.');
  }catch(error){if(epoch===state.epoch)errorMessage(error,'Could not resume this experiment',()=>resume(id));}
  finally{if(epoch===state.epoch){state.loading=false;render();}}
}
function filterPatients() {
  const query=$('patient-search').value.toLowerCase(),filtered=state.patients.filter(p=>p.patient_id.toLowerCase().includes(query)),current=state.patients.find(p=>p.patient_id===state.patient_id);
  const options=current&&!filtered.includes(current)?[current,...filtered]:filtered;
  $('patient').replaceChildren(...options.map(p=>new Option(p.patient_id,p.patient_id)));$('patient').value=state.patient_id;
  $('patient-count').textContent=query?`${filtered.length} matching record${filtered.length===1?'':'s'} · current selection kept`:`${state.patients.length} local record${state.patients.length===1?'':'s'}`;
}
$('toggle-settings').onclick=()=>{const open=$('settings').hidden;$('settings').hidden=!open;$('toggle-settings').setAttribute('aria-expanded',String(open));$('toggle-settings').textContent=open?'Hide settings':'Edit settings';};
$('quick-action').onclick=()=>{if(state.evaluation)$('results-panel').scrollIntoView({block:'start'});else if(state.run)$('reveal').click();else $('seal').click();};
if(matchMedia('(max-width:720px)').matches){$('settings').hidden=true;$('toggle-settings').setAttribute('aria-expanded','false');$('toggle-settings').textContent='Edit settings';}
document.body.dataset.view='overview';
$('settings').onsubmit=event=>{event.preventDefault();loadScope();};$('patient').onchange=()=>loadScope($('patient').value);
for(const id of ['cutoff','horizon','tolerance','organ'])$(id).addEventListener('input',invalidate);
$('restore-settings').onclick=()=>syncInputs();$('patient-search').oninput=filterPatients;
$('method').onchange=render;$('truth-view').onclick=()=>{state.truth=!state.truth;render();};
$('new-draft').onclick=()=>{state.run=null;state.evaluation=null;state.truth=false;render();notify('New draft opened. The previous experiment remains in Saved experiments.');};
$('seal').onclick=()=>write('seal',async()=>{state.run=await request('/api/experiments',{body:{patient_id:state.patient_id,spec:state.protocol}});state.evaluation=null;state.truth=false;render();notify('All three forecasts sealed. Follow-up is still hidden.');});
$('reveal').onclick=async()=>{if(!state.run||!await confirmAction('Reveal the later examination?','This records a follow-up evaluation. The sealed forecast stays unchanged, but the follow-up can no longer be considered unseen by you.','Reveal & evaluate'))return;write('reveal',async()=>{const result=await request(`/api/experiments/${encodeURIComponent(state.run.id)}/reveal`,{body:{}});state.evaluation=result.evaluation;render();notify('Follow-up evaluated against the original saved predictions.');});};
$('inspect-lesions').onclick=()=>openView('evidence',true);
$('lesion-search').oninput=renderLesions;$('lesion-sort').onchange=renderLesions;
$('toggle-chart-data').onclick=()=>{const open=$('chart-data-wrap').hidden;$('chart-data-wrap').hidden=!open;$('toggle-chart-data').setAttribute('aria-expanded',String(open));$('toggle-chart-data').textContent=open?'Hide data table':'Show data table';};
$('refresh-history').onclick=()=>loadHistory();$('more-history').onclick=()=>loadHistory(true);
$('dismiss-error').onclick=()=>{$('error').hidden=true;};
for(const b of $('workspace-tabs').querySelectorAll('[role=tab]'))b.onclick=()=>openView(b.dataset.view);
tabKeys($('workspace-tabs'),tab=>openView(tab.dataset.view));
for(const b of document.querySelectorAll('[data-close]'))b.onclick=()=>$(b.dataset.close).close();
$('help').onclick=$('setup-help').onclick=()=>$('help-dialog').showModal();
for(const [id,factor] of [['scene-in',1.2],['scene-out',1/1.2]])$(id).onclick=()=>{if(scene){scene.zoom=Math.max(.4,Math.min(3,scene.zoom*factor));scene.draw();}};
$('scene-reset').onclick=()=>{if(scene){scene.yaw=.45;scene.pitch=.25;scene.zoom=1;scene.draw();}};
document.addEventListener('keydown',event=>{if(event.ctrlKey||event.metaKey||event.altKey||event.target.closest('input,select,textarea,[contenteditable=true]')||document.querySelector('dialog[open]'))return;if(event.key==='?'){event.preventDefault();$('help-dialog').showModal();}if(event.key==='/'){event.preventDefault();$('patient-search').focus();}});
window.addEventListener('beforeunload',event=>{if(review.isDirty()){event.preventDefault();event.returnValue='';}});
new ResizeObserver(()=>drawTrajectory(state,$('method').value)).observe($('trajectory'));
async function start() {
  try{state.patients=await request('/api/patients',{channel:'patients'});if(!state.patients.length)throw new Error('No patient records are configured. Start Cancer Lab with a populated patient directory.');state.patient_id=state.patients[0].patient_id;filterPatients();await loadScope();}
  catch(error){errorMessage(error,'Could not connect to Cancer Lab',start);}
}
start();
