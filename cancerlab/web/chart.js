import {$,fmt,names,esc} from './ui.js';
export function organBurden(study,organ) {
  if(!study || study.annotation_scope!=='complete' || !study.coverage.includes(organ))return null;
  const lesions=study.lesions.filter(m=>m.organ===organ);
  if(lesions.some(m=>m.state==='not_assessed'))return null;
  return lesions.reduce((total,m)=>total+m.volume_ml,0);
}
export function drawTrajectory(state,method) {
  const c=$('trajectory'),ctx=c.getContext('2d'),w=c.clientWidth,h=c.clientHeight;
  const organ=state.protocol.organ,observed=(state.snapshot?.studies||[]).map(s=>({day:s.acquired_day,value:organBurden(s,organ),label:'Measured'}));
  const predicted=state.run?{day:state.run.artifact.target_day,value:state.run.artifact.models[method].total_ml,label:`Forecast · ${names[method]}`} : null;
  const actual=state.evaluation?{day:state.evaluation.actual_day,value:state.evaluation.scores[method].actual_total_ml,label:'Revealed'} : null;
  const all=[...observed,...(predicted?[predicted]:[]),...(actual?[actual]:[])];
  $('chart-data').innerHTML=all.length?all.map(p=>`<tr><td>${esc(p.label)}</td><td>${p.day}</td><td>${fmt(p.value)}</td></tr>`).join(''):'<tr><td colspan="3">No measurements available.</td></tr>';
  if(!w||!h||!ctx)return;
  const dpr=Math.min(devicePixelRatio||1,2);c.width=w*dpr;c.height=h*dpr;ctx.scale(dpr,dpr);
  const p={left:52,right:30,top:32,bottom:35};ctx.clearRect(0,0,w,h);
  const xs=all.map(d=>d.day),ys=all.filter(d=>d.value!==null).map(d=>d.value);
  const xmin=Math.min(0,...xs),xmax=Math.max(xmin+90,...xs),ymax=Math.max(1,...ys)*1.2;
  const x=v=>p.left+(v-xmin)/(xmax-xmin)*(w-p.left-p.right),y=v=>h-p.bottom-v/ymax*(h-p.top-p.bottom);
  ctx.font='11px system-ui';ctx.lineWidth=1;
  for(let i=0;i<4;i++) {const v=ymax*i/3;ctx.strokeStyle='#263946';ctx.beginPath();ctx.moveTo(p.left,y(v));ctx.lineTo(w-p.right,y(v));ctx.stroke();ctx.fillStyle='#a2b4c0';ctx.fillText(fmt(v),10,y(v)+4);}
  ctx.fillStyle='#a2b4c0';ctx.fillText('mL',12,16);
  const days=[...new Set(xs)].sort((a,b)=>a-b),step=Math.max(1,Math.ceil(days.length/Math.max(2,Math.floor(w/100))));
  for(let i=0;i<days.length;i++)if(i%step===0||i===days.length-1){const day=days[i];ctx.fillText(`Day ${day}`,Math.min(w-62,Math.max(34,x(day)-20)),h-10);}
  function line(points,color,dash=[]) {ctx.strokeStyle=color;ctx.fillStyle=color;ctx.setLineDash(dash);ctx.lineWidth=2;ctx.beginPath();let pen=false;for(const point of points){if(point.value===null){pen=false;continue;}if(pen)ctx.lineTo(x(point.day),y(point.value));else ctx.moveTo(x(point.day),y(point.value));pen=true;}ctx.stroke();ctx.setLineDash([]);for(const point of points)if(point.value!==null){ctx.beginPath();ctx.arc(x(point.day),y(point.value),4,0,Math.PI*2);ctx.fill();}}
  line(observed,'#77e2ce');
  if(predicted){const last=observed.filter(v=>state.snapshot.studies.find(s=>s.acquired_day===v.day)?.coverage.includes(organ)).at(-1);line(last?[last,predicted]:[predicted],'#f2c782',[5,5]);}
  if(actual&&actual.value!==null){ctx.strokeStyle='#e6eef2';ctx.lineWidth=2;ctx.beginPath();ctx.rect(x(actual.day)-5,y(actual.value)-5,10,10);ctx.stroke();}
  if(!ys.length){ctx.fillStyle='#a2b4c0';ctx.font='12px system-ui';ctx.fillText('No complete burden measurements.',p.left+8,85);}
  c.onpointermove=event=>{const bounds=c.getBoundingClientRect(),pos=event.clientX-bounds.left;const nearest=all.filter(d=>d.value!==null).sort((a,b)=>Math.abs(x(a.day)-pos)-Math.abs(x(b.day)-pos)).slice(0,2);c.title=nearest.map(v=>`${v.label}, day ${v.day}: ${fmt(v.value)} mL`).join('\n');};
}
