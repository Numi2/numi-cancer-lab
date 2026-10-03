import {esc,fmt,title,request,cancel,download,notify,confirmAction} from './ui.js';

/* Review draft UI. No match is preselected; exporting never relabels observations. */
export class ReviewWorkspace {
  constructor(host,context) {
    this.host=host;this.context=context;this.proposal=null;this.proposalText='';this.selected=new Map();this.epoch=0;this.page=0;this.busy=false;this.exported=false;
    host.innerHTML=`<section class="panel review-panel"><div class="panel-heading"><div><p class="eyebrow">HUMAN-REVIEWED CORRESPONDENCE</p><h2>Review possible lesion matches</h2></div><span class="badge subtle">No automatic assignments</span></div>
      <div class="review-upload"><div><h3>Open a local proposal</h3><p>Use the JSON file produced by the matching command. It is checked against the selected patient and loaded evidence cutoff.</p></div><label for="proposal-file" class="sr-only">Open correspondence proposal JSON</label><input id="proposal-file" type="file" accept=".json,application/json"></div>
      <p id="review-status" class="review-status footnote" role="status">No proposal loaded. Source records remain unchanged.</p>
      <div id="review-content" hidden><div id="review-summary" class="review-summary"></div><div id="review-validation" class="review-explanation"></div><div id="review-candidates" class="review-candidates"></div><div class="review-summary"><button id="review-prev" class="quiet">Previous candidates</button><span id="review-page" class="footnote"></span><button id="review-next" class="quiet">Next candidates</button></div><div id="review-unresolved" class="unresolved"></div>
      <form id="review-form"><div class="review-tools"><label for="reviewer-id">Reviewer identifier<input id="reviewer-id" pattern="[A-Za-z0-9_.\\-]{1,100}" maxlength="100" placeholder="Your research identifier" required autocomplete="off"></label><label for="review-day">Review available · day<input id="review-day" type="number" min="-100000" max="100000" step="1" required></label><button id="review-export" class="primary" disabled>Export review draft</button></div><p id="review-selection-note" class="review-selection-note" role="status">Select a candidate and record why it is the same lesion.</p></form></div>
      <details><summary>How to create and apply a proposal</summary><p class="footnote">Alignment and matching use the existing local commands. Review decisions are exported as JSON. They do not change patient records here.</p><pre>python -m cancerlab match --patient /path/to/patient.json --registration /path/to/registration.json --out /path/to/proposal.json</pre><p class="footnote">After export, use <code>review-tracks</code> with the original import manifest. That command checks file bindings and earlier identities before producing a new manifest for re-import. Keep original records for existing experiments.</p><p class="footnote">A separated candidate is not a confirmed identity. Ambiguity needs explicit review. No match does not prove a new lesion or disappearance.</p></details></section>`;
    this.file=host.querySelector('#proposal-file');this.file.onchange=()=>this.openFile();
    this.form=host.querySelector('#review-form');this.form.onsubmit=event=>{event.preventDefault();this.export();};
    this.form.oninput=()=>{this.exported=false;};
    host.querySelector('#review-prev').onclick=()=>{this.page--;this.renderCandidates();};
    host.querySelector('#review-next').onclick=()=>{this.page++;this.renderCandidates();};
  }
  get(id){return this.host.querySelector(`#${id}`);}
  isDirty(){return this.selected.size>0&&!this.exported;}
  reset(){this.epoch++;cancel('proposal');cancel('review');this.proposal=null;this.proposalText='';this.selected.clear();this.file.value='';this.busy=false;this.exported=false;this.get('review-content').hidden=true;this.get('review-status').textContent='No proposal loaded. Source records remain unchanged.';this.file.disabled=false;}
  async openFile() {
    const file=this.file.files?.[0],context=this.context();if(!file)return;
    if(!context.ready){this.get('review-status').textContent='Apply valid evidence settings before opening a proposal.';this.file.value='';return;}
    if(file.size>2_000_000){this.get('review-status').textContent='The proposal exceeds the 2 MB review limit. Reduce the matching region.';this.file.value='';return;}
    if(this.isDirty()&&!await confirmAction('Replace this review draft?','Opening another proposal clears the unsaved review decisions.','Replace draft')){this.file.value='';return;}
    const epoch=++this.epoch;this.busy=true;this.file.disabled=true;this.get('review-status').textContent='Checking proposal, source evidence, and cutoff…';
    this.proposal=null;this.proposalText='';this.selected.clear();this.get('review-content').hidden=true;
    try {
      let proposalText;try{proposalText=await file.text();JSON.parse(proposalText);}catch{throw new Error('This file is not valid JSON. Open a generated correspondence proposal.');}
      const data=await request('/api/workspace/proposal',{body:{patient_id:context.patient_id,cutoff_day:context.cutoff_day,proposal_json:proposalText},channel:'proposal'});
      if(epoch!==this.epoch)return;
      this.proposal=data;this.proposalText=proposalText;this.page=0;this.exported=false;
      const r=data.registration;
      this.get('review-content').hidden=false;
      this.get('review-status').textContent=`Verified proposal ${data.artifact_sha256.slice(0,12)} · ${data.patient_id}. Nothing has been accepted.`;
      const unresolved=data.unmatched_fixed.length+data.unmatched_moving.length;
      this.get('review-summary').innerHTML=`<div><span>Candidate pairs</span><strong>${data.candidates.length}</strong></div><div><span>Ambiguous pairs</span><strong>${data.candidates.filter(c=>c.status==='ambiguous_candidate').length}</strong></div><div><span>Unmatched observations</span><strong>${unresolved}</strong></div>`;
      this.get('review-validation').innerHTML=`<h3>${esc(r.request.fixed_study_id)} → ${esc(r.request.moving_study_id)}</h3><p>${esc(title(r.request.organ))} · Rigid alignment · fitting error ${fmt(r.fit.rmse_mm)} mm. ${r.check.count?`Independent check error: ${fmt(r.check.rmse_mm)} mm.`:'No independent check landmarks. Fit error alone does not establish whole-organ accuracy.'}</p>`;
      this.get('review-unresolved').textContent=`Unmatched earlier: ${data.unmatched_fixed.join(', ')||'none'}. Unmatched later: ${data.unmatched_moving.join(', ')||'none'}. Excluded observations: ${data.excluded_fixed.length+data.excluded_moving.length}. These are unresolved observations, not disease conclusions.`;
      this.get('review-day').value=data.available_day;this.get('review-day').min=data.available_day;this.get('review-day').max=context.cutoff_day;
      this.renderCandidates();
    }catch(error){if(epoch===this.epoch&&error.name!=='AbortError')this.get('review-status').textContent=error.message;}
    finally{if(epoch===this.epoch){this.busy=false;this.file.disabled=false;this.file.value='';this.updateCount();}}
  }
  renderCandidates() {
    const data=this.proposal;if(!data)return;
    const start=this.page*25,end=Math.min(start+25,data.candidates.length);
    this.get('review-candidates').innerHTML=data.candidates.slice(start,end).map((c,j)=>{const i=start+j,selected=this.selected.has(i);return `<article class="candidate"><div class="candidate-top"><label><input type="checkbox" data-candidate="${i}" ${selected?'checked':''}><span>${esc(c.fixed_lesion_id)} <span aria-hidden="true">→</span> ${esc(c.moving_lesion_id)}</span></label><span class="badge ${c.status==='ambiguous_candidate'?'':'subtle'}">${c.status==='ambiguous_candidate'?'Ambiguous candidate':'Separated candidate'}</span></div><p>Aligned distance ${fmt(c.distance_mm)} mm · original volumes ${fmt(c.fixed_volume_ml)} → ${fmt(c.moving_volume_ml)} mL</p><label for="reason-${i}" class="sr-only">Reason for matching ${esc(c.fixed_lesion_id)} with ${esc(c.moving_lesion_id)}</label><textarea id="reason-${i}" data-reason="${i}" placeholder="Record the evidence supporting this correspondence…" maxlength="2000" ${selected?'':'hidden'}>${esc(this.selected.get(i)||'')}</textarea></article>`;}).join('')||'<div class="empty-state"><h3>No candidate pairs</h3><p>Review the alignment and unmatched observations. This does not establish new disease or disappearance.</p></div>';
    for(const box of this.get('review-candidates').querySelectorAll('[data-candidate]'))box.onchange=()=>{
      const i=Number(box.dataset.candidate),c=data.candidates[i];
      if(box.checked){const conflict=[...this.selected.keys()].some(j=>data.candidates[j].fixed_lesion_id===c.fixed_lesion_id||data.candidates[j].moving_lesion_id===c.moving_lesion_id);if(conflict){box.checked=false;this.get('review-status').textContent='This observation is already selected in another pair. Clear that pair first. Split and merge cases need separate annotation review.';return;}this.selected.set(i,'');}
      else this.selected.delete(i);
      this.get(`reason-${i}`).hidden=!box.checked;this.exported=false;this.updateCount();if(box.checked)this.get(`reason-${i}`).focus();
    };
    for(const field of this.get('review-candidates').querySelectorAll('[data-reason]'))field.oninput=()=>{this.selected.set(Number(field.dataset.reason),field.value);this.exported=false;this.updateCount();};
    this.get('review-prev').disabled=start===0;this.get('review-next').disabled=end>=data.candidates.length;
    this.get('review-page').textContent=data.candidates.length?`${start+1}–${end} of ${data.candidates.length}`:'0 candidates';this.updateCount();
  }
  updateCount(){for(const field of this.host.querySelectorAll('input,textarea'))field.disabled=this.busy;this.get('review-export').disabled=this.busy||this.selected.size===0;this.get('review-selection-note').textContent=`${this.selected.size} pair${this.selected.size===1?'':'s'} selected. ${this.exported?'Draft exported. Original records are unchanged.':'Each pair needs a written reason. Export does not apply changes to observations.'}`;}
  async export() {
    if(this.busy||!this.proposal||!this.form.reportValidity())return;
    const context=this.context();if(!context.ready){this.get('review-status').textContent='Apply the evidence settings before exporting a review.';return;}
    const missing=[...this.selected].find(([,reason])=>!reason.trim());
    if(missing){this.page=Math.floor(missing[0]/25);this.renderCandidates();this.get(`reason-${missing[0]}`).focus();this.get('review-status').textContent='Write a reason for every selected pair.';return;}
    const epoch=this.epoch;this.busy=true;this.updateCount();
    try {
      const review={proposal_sha256:this.proposal.artifact_sha256,reviewer_id:this.get('reviewer-id').value,available_day:Number(this.get('review-day').value),links:[...this.selected].map(([i,reason])=>({fixed_lesion_id:this.proposal.candidates[i].fixed_lesion_id,moving_lesion_id:this.proposal.candidates[i].moving_lesion_id,reason:reason.trim()}))};
      const checked=await request('/api/workspace/review',{body:{patient_id:context.patient_id,cutoff_day:context.cutoff_day,proposal_json:this.proposalText,review},channel:'review'});
      if(epoch!==this.epoch)return;
      download(checked,'numi-correspondence-review.json');this.exported=true;this.get('review-status').textContent='Review draft exported. Apply it with review-tracks and the original import manifest; source observations have not changed.';notify('Review draft exported. Patient records remain unchanged.');
    }catch(error){if(epoch===this.epoch&&error.name!=='AbortError')this.get('review-status').textContent=error.message;}
    finally{if(epoch===this.epoch){this.busy=false;this.updateCount();}}
  }
}
