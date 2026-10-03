/* Slice requests are bounded, cancellable, and lazy. Forecasts are never mask overlays. */
import {request,cancel,icon,$} from './ui.js';
export class ScanViewer {
  constructor(host) {
    this.key='';this.epoch=0;this.selection=null;this.cards=[];this.timers=new Map();this.meta=null;
    this.panel=document.createElement('section');this.panel.className='panel scan-panel';
    this.panel.innerHTML=`<div class="panel-heading"><div><p class="eyebrow">SOURCE IMAGES &amp; MEASURED ANNOTATIONS</p><h2>CT inspection</h2></div><span class="badge subtle">Measured only</span></div>
      <p id="scan-status" class="footnote scan-status" role="status">Select an observation to inspect its local scan.</p>
      <div id="scan-empty" class="empty-state">${icon('scan')}<h3>Connect local CT images</h3><p>The demonstration includes measurements, not patient scans. Load imported records and point the local server to the source dataset to inspect actual images.</p><button id="scan-setup" class="secondary">View setup instructions</button><button id="scan-retry" class="quiet" hidden>Retry images</button></div>
      <form id="scan-window" class="scan-window" hidden><label for="scan-preset">Window preset<select id="scan-preset"><option value="40,400">Soft tissue</option><option value="-600,1500">Lung</option><option value="400,1800">Bone</option><option value="custom">Custom</option></select></label><label>Center<input name="center" aria-label="CT window center" type="number" value="40" min="-5000" max="5000" required></label><label>Width<input name="width" aria-label="CT window width" type="number" value="400" min="1" max="10000" required></label><label>Mask opacity<input name="opacity" aria-label="Mask opacity" type="range" value="0.4" min="0" max="1" step="0.05"></label><label class="mask-switch"><input id="mask-visible" type="checkbox" checked>Show measured mask</label><button class="secondary" type="submit">Apply window</button></form>
      <div class="scan-grid" hidden></div><p class="footnote panel-note">Source-grid slices, not aligned comparisons. Unobserved areas remain unknown. Presets adjust display only; they do not alter measurements. This is a research viewer, not diagnostic software.</p>`;
    host.append(this.panel);this.status=this.panel.querySelector('#scan-status');this.form=this.panel.querySelector('form');this.grid=this.panel.querySelector('.scan-grid');this.empty=this.panel.querySelector('#scan-empty');
    this.form.onsubmit=event=>{event.preventDefault();if(this.form.reportValidity())this.refresh();};
    this.panel.querySelector('#scan-preset').onchange=event=>{if(event.target.value==='custom')return;const [center,width]=event.target.value.split(',');this.form.elements.center.value=center;this.form.elements.width.value=width;this.refresh();};
    for(const name of ['center','width'])this.form.elements[name].oninput=()=>{this.panel.querySelector('#scan-preset').value='custom';};
    this.form.elements.opacity.oninput=()=>{clearTimeout(this.opacityTimer);this.opacityTimer=setTimeout(()=>this.refresh(),120);};
    this.panel.querySelector('#mask-visible').onchange=()=>this.refresh();
    this.panel.querySelector('#scan-setup').onclick=()=>$('help-dialog').showModal();
    this.panel.querySelector('#scan-retry').onclick=()=>{const s=this.selection;this.key='';this.select(s);};
    $('scan-dialog').addEventListener('close',()=>this.restoreCard());
  }
  url(endpoint,extras={}) {const s=this.selection;const params=new URLSearchParams({organ:s.organ,cutoff_day:s.cutoff_day,...extras});if(s.run_id)params.set('run_id',s.run_id);return `/api/patients/${encodeURIComponent(s.patient_id)}/studies/${encodeURIComponent(s.study_id)}/${endpoint}?${params}`;}
  stop(){for(const key of ['scan-meta','scan-axial','scan-coronal','scan-sagittal'])cancel(key);for(const timer of this.timers.values())clearTimeout(timer);this.timers=new Map();clearTimeout(this.opacityTimer);}
  suspend(){this.stop();this.key='';this.epoch++;}
  async select(selection) {
    const key=JSON.stringify(selection);if(key===this.key)return;
    this.stop();$('scan-dialog').close();this.restoreCard();this.key=key;this.selection=selection;const epoch=++this.epoch;
    for(const card of this.cards)card._resize?.disconnect();
    this.grid.replaceChildren();this.cards=[];this.grid.hidden=true;this.form.hidden=true;this.empty.hidden=false;this.panel.querySelector('#scan-retry').hidden=true;
    if(!selection){this.status.textContent='Select an available observation to inspect its local scan.';return;}
    this.status.textContent='Checking local image evidence…';
    try {
      const meta=await request(this.url('image'),{channel:'scan-meta'});if(epoch!==this.epoch)return;this.meta=meta;
      this.status.textContent=meta.configured?`${meta.synthetic?'SYNTHETIC VOXEL FIXTURE':'Verified scan '+meta.scan_sha256.slice(0,12)} · ${meta.overlay_available?'measured mask available':'no measured mask available'}`:meta.notice;
      if(!meta.configured)return;
      this.empty.hidden=true;this.form.hidden=false;this.grid.hidden=false;
      this.panel.querySelector('#mask-visible').disabled=!meta.overlay_available;
      for(const [plane,axis] of [['axial',2],['coronal',1],['sagittal',0]]) {
        const card=document.createElement('article');card.className='scan-card';card.dataset.plane=plane;
        card.innerHTML=`<div class="scan-card-heading"><h3>${plane[0].toUpperCase()+plane.slice(1)}</h3><button class="quiet expand-scan" aria-label="Expand ${plane} scan">Expand ↗</button></div><div class="scan-image-wrap"><img alt="Measured ${plane} CT slice" hidden><span class="scan-top"></span><span class="scan-right"></span><span class="scan-bottom"></span><span class="scan-left"></span></div><div class="slice-controls"><button class="icon-button slice-prev" aria-label="Previous ${plane} slice">−</button><input type="range" min="0" max="${meta.shape_ras[axis]-1}" value="${Math.floor((meta.shape_ras[axis]-1)/2)}" aria-label="${plane} slice"><button class="icon-button slice-next" aria-label="Next ${plane} slice">+</button></div><p class="footnote" role="status"></p>`;
        let timer;const slider=card.querySelector('input');
        slider.oninput=()=>{clearTimeout(timer);timer=setTimeout(()=>{if(epoch===this.epoch)this.draw(card,epoch);},80);this.timers.set(plane,timer);};
        for(const [cls,step] of [['.slice-prev',-1],['.slice-next',1]])card.querySelector(cls).onclick=()=>{slider.value=Math.max(0,Math.min(Number(slider.max),Number(slider.value)+step));this.draw(card,epoch);};
        card.querySelector('.expand-scan').onclick=()=>this.expand(card);
        this.grid.append(card);this.cards.push(card);
        card._resize=new ResizeObserver(()=>this.sizeImage(card));card._resize.observe(card.querySelector('.scan-image-wrap'));
      }
      this.refresh();
    }catch(error){if(epoch===this.epoch&&error.name!=='AbortError'){this.status.textContent=error.message;this.panel.querySelector('#scan-retry').hidden=false;}}
  }
  expand(card){this.restoreCard();this.placeholder=document.createComment('expanded source slice');card.replaceWith(this.placeholder);this.expanded=card;card.classList.add('expanded');$('scan-expanded').append(card);$('scan-dialog-title').textContent=`${card.dataset.plane[0].toUpperCase()+card.dataset.plane.slice(1)} · source CT`;$('scan-dialog').showModal();}
  restoreCard(){if(this.expanded){this.expanded.classList.remove('expanded');this.placeholder?.replaceWith(this.expanded);const trigger=this.expanded.querySelector('.expand-scan');requestAnimationFrame(()=>{if(trigger.isConnected)trigger.focus({preventScroll:true});});this.expanded=null;this.placeholder=null;}}
  sizeImage(card){
    if(!card._ratio)return;
    const box=card.querySelector('.scan-image-wrap'),img=card.querySelector('img'),style=getComputedStyle(box);
    const width=box.clientWidth-parseFloat(style.paddingLeft)-parseFloat(style.paddingRight);
    const height=box.clientHeight-parseFloat(style.paddingTop)-parseFloat(style.paddingBottom);
    const size=Math.max(0,Math.min(width,height*card._ratio));
    img.style.width=`${size}px`;img.style.height=`${size/card._ratio}px`;
  }
  refresh(){if(this.form.reportValidity()&&this.selection)for(const card of this.cards)this.draw(card,this.epoch);}
  async draw(card,epoch) {
    const plane=card.dataset.plane,note=card.querySelector('p'),img=card.querySelector('img'),slider=card.querySelector('input');
    const ticket=(card._ticket||0)+1;card._ticket=ticket;
    const values={center:this.form.elements.center.value,width:this.form.elements.width.value,opacity:this.panel.querySelector('#mask-visible').checked?this.form.elements.opacity.value:0};
    note.textContent='Updating source slice…';card.setAttribute('aria-busy','true');
    card.querySelector('.slice-prev').disabled=Number(slider.value)===0;card.querySelector('.slice-next').disabled=Number(slider.value)===Number(slider.max);
    try {
      const data=await request(this.url('slice',{plane,index:slider.value,...values}),{channel:`scan-${plane}`});
      if(epoch!==this.epoch||ticket!==card._ticket)return;
      img.src=`data:image/png;base64,${data.png_base64}`;img.style.aspectRatio=`${data.width*data.pixel_spacing_mm[1]} / ${data.height*data.pixel_spacing_mm[0]}`;img.hidden=false;card._ratio=data.width*data.pixel_spacing_mm[1]/(data.height*data.pixel_spacing_mm[0]);this.sizeImage(card);
      for(const side of ['top','right','bottom','left'])card.querySelector(`.scan-${side}`).textContent=data.orientation[side];
      img.alt=`Measured ${plane} CT, slice ${data.index+1} of ${data.slice_count}, RAS ${data.position_ras_mm.toFixed(1)} millimetres${Number(values.opacity)>0&&this.meta.overlay_available?', with measured mask':''}`;
      note.textContent=`Slice ${data.index+1}/${data.slice_count} · RAS ${data.position_ras_mm.toFixed(1)} mm`;slider.setAttribute('aria-valuetext',`Slice ${data.index+1} of ${data.slice_count}`);
    }catch(error){if(epoch===this.epoch&&ticket===card._ticket&&error.name!=='AbortError'){img.hidden=true;note.textContent=error.message;}}
    finally{if(epoch===this.epoch&&ticket===card._ticket)card.setAttribute('aria-busy','false');}
  }
}
