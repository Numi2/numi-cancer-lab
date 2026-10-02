/* Source CT inspection. Predictions never become image overlays. */
export class ScanViewer {
  constructor() {
    this.key = ''; this.epoch = 0; this.selection = null; this.requests = new Map();
    this.panel = document.createElement('section');
    this.panel.className = 'panel scan-panel';
    this.panel.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">MEASURED SOURCE IMAGES</p><h2>CT &amp; annotation inspection</h2></div><span class="mini-label">LOCAL FILES ONLY</span></div>
      <p id="scan-status" class="footnote" role="status">Select an observation to inspect its local scan.</p>
      <form id="scan-window" class="scan-window" hidden><label>Window center<input name="center" aria-label="CT window center" type="number" value="40" min="-5000" max="5000" required></label><label>Window width<input name="width" aria-label="CT window width" type="number" value="400" min="1" max="10000" required></label><label>Mask opacity<input name="opacity" aria-label="Mask opacity" type="number" value="0.4" min="0" max="1" step="0.1" required></label><button class="secondary" type="submit">Apply window</button></form>
      <div class="scan-grid" hidden></div><p class="footnote">Measured masks only; no predicted boundaries. Each examination uses its own coordinate frame. Oblique grids require explicit resampling. Research display, not diagnostic viewing.</p>`;
    document.querySelector('.work-grid').after(this.panel);
    this.status = this.panel.querySelector('#scan-status');
    this.form = this.panel.querySelector('form'); this.grid = this.panel.querySelector('.scan-grid');
    this.form.onsubmit = event => {event.preventDefault(); if(this.form.reportValidity()) this.refresh();};
  }
  async request(path, key) {
    this.requests.get(key)?.abort();
    const controller = new AbortController(); this.requests.set(key, controller);
    try {
      const response = await fetch(path, {signal: controller.signal}); const body = await response.json();
      if(!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Image request rejected');
      return body;
    } finally { if(this.requests.get(key) === controller) this.requests.delete(key); }
  }
  url(endpoint, extras = {}) {
    const s = this.selection;
    const params = new URLSearchParams({organ:s.organ, cutoff_day:s.cutoff_day, ...extras});
    if(s.run_id) params.set('run_id', s.run_id);
    return `/api/patients/${encodeURIComponent(s.patient_id)}/studies/${encodeURIComponent(s.study_id)}/${endpoint}?${params}`;
  }
  async select(selection) {
    const key = JSON.stringify(selection);
    if(key === this.key) return;
    this.key = key; this.selection = selection; const epoch = ++this.epoch;
    for(const request of this.requests.values()) request.abort(); this.requests.clear();
    this.grid.replaceChildren(); this.grid.hidden = true; this.form.hidden = true;
    if(!selection) {this.status.textContent = 'Select an available observation to inspect its local scan.'; return;}
    this.status.textContent = 'Checking local image evidence…';
    try {
      const meta = await this.request(this.url('image'), 'metadata');
      if(epoch !== this.epoch) return;
      this.status.textContent = meta.configured ? `${meta.synthetic ? "SYNTHETIC VOXEL FIXTURE" : "Verified scan " + meta.scan_sha256.slice(0,12)} · ${meta.overlay_available ? 'measured mask available' : 'no mask evidence available'}` : meta.notice;
      if(!meta.configured) return;
      this.form.hidden = false; this.grid.hidden = false;
      for(const [plane, axis] of [['axial',2],['coronal',1],['sagittal',0]]) {
        const card = document.createElement('div'); card.className = 'scan-card'; card.dataset.plane = plane;
        card.innerHTML = `<h3>${plane[0].toUpperCase()+plane.slice(1)}</h3><div class="scan-image-wrap"><img alt="Measured ${plane} CT slice" hidden><span class="scan-top"></span><span class="scan-right"></span><span class="scan-bottom"></span><span class="scan-left"></span></div><input type="range" min="0" max="${meta.shape_ras[axis]-1}" value="${Math.floor((meta.shape_ras[axis]-1)/2)}" aria-label="${plane} slice"><p class="footnote" role="status"></p>`;
        let timer; card.querySelector('input').oninput = () => {clearTimeout(timer); timer=setTimeout(()=>{if(epoch===this.epoch)this.draw(card,epoch);},100);};
        this.grid.append(card);
      }
      this.refresh();
    } catch(error) {if(epoch === this.epoch && error.name !== 'AbortError') this.status.textContent = error.message;}
  }
  refresh() {for(const card of this.grid.children) this.draw(card,this.epoch);}
  async draw(card, epoch) {
    const plane = card.dataset.plane, note = card.querySelector('p'), img = card.querySelector('img');
    const ticket = (card._ticket || 0) + 1; card._ticket = ticket;
    const values = Object.fromEntries(new FormData(this.form));
    note.textContent = 'Loading source slice…'; img.hidden = true;
    try {
      const data = await this.request(this.url('slice',{plane,index:card.querySelector('input').value,...values}), plane);
      if(epoch !== this.epoch || ticket !== card._ticket) return;
      img.src = `data:image/png;base64,${data.png_base64}`;
      img.style.aspectRatio = `${data.width*data.pixel_spacing_mm[1]} / ${data.height*data.pixel_spacing_mm[0]}`;
      img.hidden = false;
      for(const side of ['top','right','bottom','left']) card.querySelector(`.scan-${side}`).textContent = data.orientation[side];
      note.textContent = `Slice ${data.index+1}/${data.slice_count} · RAS position ${data.position_ras_mm.toFixed(1)} mm`;
    } catch(error) {if(epoch === this.epoch && ticket === card._ticket && error.name !== 'AbortError') note.textContent = error.message;}
  }
}
