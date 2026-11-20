// Render the same body-coordinate meshes used by the Python setup studio.
const folder = new URL('./assets/airframes/', import.meta.url);
const models = new Map();
async function asset(name) {
  const response = await fetch(new URL(name, folder));
  if (!response.ok) throw Error('Airframe unavailable');
  return response.text();
}
async function geometry(key) {
  const [obj, mtl] = await Promise.all([asset(key + '.obj'), asset('areion.mtl')]);
  const verts = [], faces = [], colors = {};
  let material;
  for (const line of mtl.split('\n')) {
    const [tag, ...v] = line.trim().split(/\s+/);
    if (tag === 'newmtl') material = v[0];
    if (tag === 'Kd') colors[material] = v.map(Number);
  }
  for (const line of obj.split('\n')) {
    const [tag, ...v] = line.trim().split(/\s+/);
    if (tag === 'v') verts.push(v.map(Number));
    if (tag === 'usemtl') material = v[0];
    if (tag === 'f') faces.push({indices: v.map(s => Number(s) - 1), color: colors[material]});
  }
  return {verts, faces};
}
function degrees(x) {return x * Math.PI / 180;}
function rotate([x,y,z], roll, pitch, yaw) {
  let a = degrees(roll), c = Math.cos(a), s = Math.sin(a);
  [x,z] = [c*x + s*z, -s*x + c*z];
  a = degrees(pitch); c = Math.cos(a); s = Math.sin(a);
  [y,z] = [c*y - s*z, s*y + c*z];
  a = degrees(-yaw); c = Math.cos(a); s = Math.sin(a);
  return [c*x - s*y, s*x + c*y, z];
}

export function airframe(canvas, profile='areion450', orientation=[0,0,0], fitGuide=false) {
  const key = profile === 'areion250' ? profile : 'areion450';
  const sig = [key, fitGuide, ...orientation.map(v=>Math.round(v*2)/2), canvas.clientWidth, canvas.clientHeight].join('/');
  if (canvas.dataset.pose === sig) return;
  canvas.dataset.pose = sig;
  if (!models.has(key)) models.set(key, geometry(key).catch(error=>{models.delete(key); throw error;}));
  models.get(key).then(mesh=>{
    if (!canvas.isConnected || canvas.dataset.pose !== sig) return;
    const ctx = canvas.getContext('2d');
    const w = canvas.clientWidth || 300, h = canvas.clientHeight || 165;
    const pixel = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(w*pixel); canvas.height = Math.round(h*pixel);
    ctx.scale(pixel,pixel);
    const az = degrees(28), el = degrees(32);
    const projected = mesh.verts.map(v=>{
      const [x,y,z] = rotate(v,...orientation);
      const d = y*Math.cos(az) - x*Math.sin(az);
      return [x*Math.cos(az)+y*Math.sin(az), -(d*Math.sin(el)+z*Math.cos(el)), d*Math.cos(el)-z*Math.sin(el)];
    });
    let scale = Math.min(w*.35, h*.49), centerX = w/2, centerY = h*.55;
    if (fitGuide) {
      // Leave room for the position labels even when the aircraft stands on an edge.
      const xs = projected.map(v=>v[0]), ys = projected.map(v=>v[1]);
      const left = Math.min(...xs), right = Math.max(...xs), top = Math.min(...ys), bottom = Math.max(...ys);
      scale = Math.min(scale, w*.89/(right-left), h*.68/(bottom-top));
      centerX = w/2 - (right+left)*scale/2;
      centerY = h/2 - (top+bottom)*scale/2;
    }
    const vertices = projected.map(([x,y,z])=>[centerX+x*scale,centerY+y*scale,z]);
    const drawn = mesh.faces.map(f=>{
      const p = f.indices.map(i=>vertices[i]);
      return {p,depth:p.reduce((s,v)=>s+v[2],0)/p.length, rgb:f.color};
    }).sort((a,b)=>b.depth-a.depth);
    for (const {p,rgb} of drawn) {
      const u=p[1].map((v,i)=>v-p[0][i]), v=p[2].map((n,i)=>n-p[0][i]);
      const norm=[(u[1]*v[2]-u[2]*v[1])/scale,(u[2]*v[0]-u[0]*v[2])/scale,(u[0]*v[1]-u[1]*v[0])/(scale*scale)];
      const illum=.73+.3*Math.abs((norm[0]*-.35+norm[1]*-.6+norm[2]*.65)/(Math.hypot(...norm)||1));
      ctx.fillStyle='rgb('+rgb.map(c=>Math.min(255,Math.round(c*255*illum))).join(',')+')';
      ctx.beginPath(); ctx.moveTo(p[0][0],p[0][1]); for (const q of p.slice(1)) ctx.lineTo(q[0],q[1]);
      ctx.closePath(); ctx.fill();
    }
  }).catch(()=>{if (canvas.isConnected) canvas.setAttribute('aria-label','Airframe image unavailable');});
}
