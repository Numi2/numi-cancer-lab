/* Shared UI primitives; no dependencies, persistent patient storage, or telemetry. */
export const $ = id => document.getElementById(id);
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const fmt = value => value === null || value === undefined ? 'Unknown' : Number(value).toLocaleString(undefined,{maximumFractionDigits:2});
export const title = value => String(value || '').replaceAll('_',' ').replace(/^./, c => c.toUpperCase());
export const icon = name => `<svg class="icon" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
export const names = {no_change:'No change',linear:'Linear growth',exponential:'Exponential growth'};
const requests = new Map();
export function cancel(channel) {requests.get(channel)?.abort(); requests.delete(channel);}
export async function request(path, {body, channel, timeout=20000} = {}) {
  if(channel) cancel(channel);
  const controller = new AbortController();
  if(channel) requests.set(channel,controller);
  let timedOut = false;
  const timer = setTimeout(() => {timedOut=true;controller.abort();},timeout);
  try {
    const response = await fetch(path,{signal:controller.signal,...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Cancerlab-Request':'local-research'},body:JSON.stringify(body)})});
    let data;
    try {data=await response.json();} catch {throw new Error('The local server returned an unreadable response. Check that Cancer Lab is running.');}
    if(!response.ok) {
      const detail=Array.isArray(data.detail)?data.detail.map(e=>`${e.loc?.slice(1).join(' · ') || 'Input'}: ${e.msg}`).join('; '):data.detail;
      throw new Error(String(detail || `Local request failed (${response.status})`).slice(0,1000));
    }
    return data;
  } catch(error) {
    if(timedOut) throw new Error('The local server did not respond in time. A save may still have completed; check Saved experiments before saving again.');
    if(error instanceof TypeError) throw new Error('Cannot reach the local server. Keep it running, then retry.');
    throw error;
  } finally {clearTimeout(timer);if(requests.get(channel)===controller)requests.delete(channel);}
}
export function download(value, filename) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);
}
let toastTimer;
export function notify(message) {clearTimeout(toastTimer);$('toast').textContent=message;toastTimer=setTimeout(()=>{$('toast').textContent='';},6000);}
export function confirmAction(heading, message, label='Continue') {
  const dialog=$('confirm-dialog');$('confirm-title').textContent=heading;$('confirm-copy').textContent=message;$('confirm-primary').textContent=label;
  return new Promise(resolve=>{dialog.returnValue='cancel';dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});dialog.showModal();$('confirm-cancel').focus();});
}
export async function copyText(text, button) {
  try {await navigator.clipboard.writeText(text);notify('Copied to clipboard.');}
  catch {notify('Clipboard unavailable. Select and copy the visible text.');button?.closest('details')?.setAttribute('open','');}
}
export function tabKeys(container, onActivate) {
  container.addEventListener('keydown',event=>{
    const tabs=[...container.querySelectorAll('[role=tab]')];const index=tabs.indexOf(document.activeElement);
    if(index<0)return;
    const next=event.key==='ArrowRight'?(index+1)%tabs.length:event.key==='ArrowLeft'?(index+tabs.length-1)%tabs.length:event.key==='Home'?0:event.key==='End'?tabs.length-1:null;
    if(next!==null){event.preventDefault();onActivate(tabs[next]);tabs[next].focus();}
  });
}
