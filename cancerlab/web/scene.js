// CPU projection keeps inspection usable when WebGL is unavailable.
class CanvasLesionScene {
  constructor(canvas) {
    this.canvas=canvas;this.ctx=canvas.getContext('2d');this.items=[];this.yaw=.45;this.pitch=.25;this.zoom=1;
    if(!this.ctx)throw new Error('Canvas rendering unavailable');
    canvas.dataset.renderer='canvas-projection';let pointer=null;
    canvas.addEventListener('pointerdown',e=>{pointer=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{if(!pointer)return;this.yaw+=(e.clientX-pointer[0])*.008;this.pitch=Math.max(-1.3,Math.min(1.3,this.pitch+(e.clientY-pointer[1])*.008));pointer=[e.clientX,e.clientY];this.draw();});
    for(const event of ['pointerup','pointercancel'])canvas.addEventListener(event,()=>{pointer=null;});
    canvas.addEventListener('wheel',e=>{if(document.activeElement!==canvas)return;e.preventDefault();this.zoom=Math.max(.4,Math.min(3,this.zoom*Math.exp(-e.deltaY*.001)));this.draw();},{passive:false});
    canvas.addEventListener('keydown',e=>{if(!e.key.startsWith('Arrow'))return;e.preventDefault();if(e.key==='ArrowLeft')this.yaw-=.12;if(e.key==='ArrowRight')this.yaw+=.12;if(e.key==='ArrowUp')this.pitch-=.12;if(e.key==='ArrowDown')this.pitch+=.12;this.draw();});
    this.observer=new ResizeObserver(()=>this.draw());this.observer.observe(canvas);
  }
  set(items,selected=null){this.items=items;this.selected=selected;this.draw();}
  draw(){
    const c=this.canvas,ctx=this.ctx,dpr=Math.min(devicePixelRatio||1,2),w=c.clientWidth,h=c.clientHeight;
    c.width=Math.max(1,w*dpr);c.height=Math.max(1,h*dpr);ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
    const items=this.items.filter(i=>i.center&&Number.isFinite(i.volume)&&i.volume>0);
    const center=items.length?[0,1,2].map(a=>items.reduce((s,i)=>s+i.center[a],0)/items.length):[0,0,0];
    const radius=v=>Math.cbrt(v*1000*3/(4*Math.PI));
    const extent=Math.max(55,...items.map(i=>Math.hypot(...i.center.map((v,a)=>v-center[a]))+radius(i.volume)*1.5));
    const scale=Math.min(w,h)*.42/extent*this.zoom;
    const project=point=>{let [x,y,z]=point.map((v,a)=>v-center[a]);[y,z]=[z,-y];const a=x*Math.cos(this.yaw)+z*Math.sin(this.yaw),b=-x*Math.sin(this.yaw)+z*Math.cos(this.yaw);return [w/2+a*scale,h/2-(y*Math.cos(this.pitch)-b*Math.sin(this.pitch))*scale,y*Math.sin(this.pitch)+b*Math.cos(this.pitch)];};
    ctx.lineWidth=1;ctx.strokeStyle='#203b4160';
    for(let i=-80;i<=80;i+=20){for(const segment of [[[i,-80,-30],[i,80,-30]],[[-80,i,-30],[80,i,-30]]]){const a=project(segment[0]),b=project(segment[1]);ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();}}
    const sorted=[...items].sort((a,b)=>Number(a.wire)-Number(b.wire)||project(a.center)[2]-project(b.center)[2]);
    for(const item of sorted){
      const [x,y]=project(item.center),r=radius(item.volume)*scale;ctx.globalAlpha=this.selected&&this.selected!==item.id ? .35:1;
      if(item.wire){
        ctx.strokeStyle='#e6bc73';ctx.lineWidth=1;
        for(let j=0;j<8;j++){ctx.beginPath();for(let i=0;i<=64;i++){const t=i*Math.PI*2/64,p=j*Math.PI/8,rr=radius(item.volume);const q=project([item.center[0]+rr*Math.cos(t)*Math.cos(p),item.center[1]+rr*Math.cos(t)*Math.sin(p),item.center[2]+rr*Math.sin(t)]);if(i)ctx.lineTo(q[0],q[1]);else ctx.moveTo(q[0],q[1]);}ctx.stroke();}
      }else{
        const g=ctx.createRadialGradient(x-r*.35,y-r*.4,r*.05,x,y,r);g.addColorStop(0,'#a2f7df');g.addColorStop(.55,'#42ae96');g.addColorStop(1,'#143f3a');ctx.fillStyle=g;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#70dcc780';ctx.stroke();
        ctx.fillStyle='#bfe9df';ctx.font='11px system-ui';ctx.fillText(`${item.id} · ${item.volume.toFixed(2)} mL`,x+r+10,y-3);
      }
      ctx.globalAlpha=1;
    }
    ctx.fillStyle='#738e97';ctx.font='9px system-ui';ctx.fillText('3D coordinates · CPU projection',18,22);
  }
}

// Local WebGL2 renderer. Spheres encode measured volume, not actual tumor surfaces.
export class LesionScene {
  constructor(canvas) {
    this.canvas = canvas; this.items = []; this.yaw = 0.45; this.pitch = 0.25; this.zoom = 1;
    this.gl = canvas.getContext('webgl2', {antialias:true, alpha:true});
    if (!this.gl) return new CanvasLesionScene(canvas);
    canvas.dataset.renderer='webgl2';
    const gl = this.gl;
    const compile = (type, source) => {
      const s = gl.createShader(type); gl.shaderSource(s, source); gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s));
      return s;
    };
    const vs = compile(gl.VERTEX_SHADER, `#version 300 es
      in vec3 position; in vec3 normal;
      uniform vec2 angles; uniform float aspect; uniform float zoom; uniform float extent;
      uniform vec3 center; out float light;
      void main(){
        float c=cos(angles.x),s=sin(angles.x),a=cos(angles.y),b=sin(angles.y);
        mat3 r=mat3(c,0.,-s,0.,1.,0.,s,0.,c);
        mat3 q=mat3(1.,0.,0.,0.,a,b,0.,-b,a);
        vec3 p=q*r*(position-center)/extent*zoom;
        vec3 n=normalize(q*r*normal);
        light=.38+.62*max(0.,dot(n,normalize(vec3(-.4,.6,1.))));
        gl_Position=vec4(p.x/aspect,p.y,-p.z*.3,1.);
      }`);
    const fs = compile(gl.FRAGMENT_SHADER, `#version 300 es
      precision highp float; in float light; uniform vec3 color; uniform bool wire;
      out vec4 result; void main(){result=vec4(color*(wire?1.:light),1.);}`);
    this.program=gl.createProgram(); gl.attachShader(this.program,vs);gl.attachShader(this.program,fs);gl.linkProgram(this.program);
    if (!gl.getProgramParameter(this.program,gl.LINK_STATUS)) throw new Error('Shader linking failed');
    this.buffer=gl.createBuffer();
    let pointer=null;
    canvas.addEventListener('pointerdown',e=>{pointer=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{if(!pointer)return;this.yaw+=(e.clientX-pointer[0])*.008;this.pitch=Math.max(-1.3,Math.min(1.3,this.pitch+(e.clientY-pointer[1])*.008));pointer=[e.clientX,e.clientY];this.draw();});
    canvas.addEventListener('pointerup',()=>{pointer=null;});canvas.addEventListener('pointercancel',()=>{pointer=null;});
    canvas.addEventListener('wheel',e=>{if(document.activeElement!==canvas)return;e.preventDefault();this.zoom=Math.max(.4,Math.min(3,this.zoom*Math.exp(-e.deltaY*.001)));this.draw();},{passive:false});
    canvas.addEventListener('keydown',e=>{if(!e.key.startsWith('Arrow'))return;e.preventDefault();if(e.key==='ArrowLeft')this.yaw-=.12;if(e.key==='ArrowRight')this.yaw+=.12;if(e.key==='ArrowUp')this.pitch-=.12;if(e.key==='ArrowDown')this.pitch+=.12;this.draw();});
    this.resizeObserver=new ResizeObserver(()=>this.draw());this.resizeObserver.observe(canvas);
  }
  set(items, selected=null) {this.items=items;this.selected=selected;this.draw();}
  draw() {
    const gl=this.gl,c=this.canvas,dpr=Math.min(window.devicePixelRatio||1,2);
    c.width=Math.max(1,Math.round(c.clientWidth*dpr));c.height=Math.max(1,Math.round(c.clientHeight*dpr));
    gl.viewport(0,0,c.width,c.height);gl.clearColor(0,0,0,0);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);gl.enable(gl.DEPTH_TEST);gl.useProgram(this.program);
    const loc=n=>gl.getUniformLocation(this.program,n);
    gl.uniform2f(loc('angles'),this.yaw,this.pitch);gl.uniform1f(loc('aspect'),c.width/c.height);gl.uniform1f(loc('zoom'),this.zoom);
    const valid=this.items.filter(i=>i.center&&Number.isFinite(i.volume)&&i.volume>0);
    const center=valid.length?[0,1,2].map(a=>valid.reduce((sum,i)=>sum+i.center[a],0)/valid.length):[0,0,0];
    const world=([x,y,z])=>[x,z,-y];
    const extent=Math.max(55,...valid.map(i=>Math.hypot(...i.center.map((v,a)=>v-center[a]))+Math.cbrt(i.volume*1000*3/(4*Math.PI))*1.5));
    gl.uniform3fv(loc('center'),world(center));gl.uniform1f(loc('extent'),extent*1.15);
    for(const item of valid){
      const r=Math.cbrt(item.volume*1000*3/(4*Math.PI)),data=[],rows=18,cols=28;
      const vertex=(i,j)=>{const p=Math.PI*i/rows,t=2*Math.PI*j/cols,n=[Math.sin(p)*Math.cos(t),Math.sin(p)*Math.sin(t),Math.cos(p)];return [...world(n.map((v,a)=>item.center[a]+r*v)),...world(n)];};
      for(let i=0;i<rows;i++)for(let j=0;j<cols;j++){
        const a=vertex(i,j),b=vertex(i+1,j),d=vertex(i,j+1),e=vertex(i+1,j+1);
        data.push(...(item.wire?[...a,...b,...a,...d]:[...a,...b,...d,...d,...b,...e]));
      }
      gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(data),gl.DYNAMIC_DRAW);
      for(const [name,offset] of [['position',0],['normal',12]]){const p=gl.getAttribLocation(this.program,name);gl.enableVertexAttribArray(p);gl.vertexAttribPointer(p,3,gl.FLOAT,false,24,offset);}
      let color=item.wire?[.94,.73,.38]:[.3,.84,.72];
      if(this.selected&&this.selected!==item.id)color=color.map(v=>v*.45);
      gl.uniform3fv(loc('color'),color);gl.uniform1i(loc('wire'),item.wire?1:0);
      gl.drawArrays(item.wire?gl.LINES:gl.TRIANGLES,0,data.length/6);
    }
  }
}
