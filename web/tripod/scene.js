import * as THREE from '../assembly/three.module.min.js';
import {loadGLB} from '../assembly/glb-loader.js';
import {CanvasRenderer} from '../assembly/js/canvas-renderer.js';
import {loadAssemblyTripod, MOTOR_LAYOUT} from './tripod-assembly-model.js';

const rad = Math.PI/180;
const views = {isometric:[.66,.32], rear:[Math.PI,.17], front:[0,.17], left:[Math.PI/2,.23], right:[-Math.PI/2,.23], top:[0,1.49]};
function disposeTree(group) {
  const geometries=new Set(), materials=new Set();
  group.traverse(part=>{
    if (part.geometry) geometries.add(part.geometry);
    for (const material of [part.material].flat()) if (material) materials.add(material);
  });
  geometries.forEach(g=>g.dispose()); materials.forEach(m=>m.dispose());
}
export function createScene(stage, onStatus, onDisturb, signal) {
  let renderer;
  try {
    const canvas=document.createElement('canvas');
    const context=canvas.getContext('webgl2',{antialias:true,alpha:false});
    renderer=context?new THREE.WebGLRenderer({canvas,context}):new CanvasRenderer(THREE);
  }
  catch { renderer = new CanvasRenderer(THREE); }
  const canvas=renderer.domElement;
  canvas.setAttribute('role','img'); canvas.setAttribute('aria-label','F450 quadcopter on a three-axis tripod');
  stage.prepend(canvas);
  const scene=new THREE.Scene(), stageGroup=new THREE.Group(), pivot=new THREE.Group();
  scene.background=new THREE.Color('#112431');
  scene.add(stageGroup,pivot);
  const soft=renderer.isCanvasRenderer;
  renderer.setPixelRatio(Math.min(window.devicePixelRatio||1,soft?1.25:1.75));
  const camera=new THREE.PerspectiveCamera(39,1,.1,65);
  const light=new THREE.DirectionalLight(0xfff1dd,2.8); light.position.set(3,8,6);
  const rim=new THREE.DirectionalLight(0xbdefff,1.9); rim.position.set(-5,4,-4);
  scene.add(light,rim,new THREE.HemisphereLight(0xdcefff,0x7395a4,1.75));
  if (!soft) scene.add(new THREE.GridHelper(17,22,0x47616c,0x263f4b));
  const silver=new THREE.MeshStandardMaterial({color:0x9ebac4,metalness:.55,roughness:.35});
  const dark=new THREE.MeshStandardMaterial({color:0x354a56,metalness:.35,roughness:.5});
  const mint=new THREE.MeshStandardMaterial({color:0x66d9bf,metalness:.28,roughness:.4});
  const rod=(a,b,r1,r2,material)=>{
    const A=new THREE.Vector3(...a), B=new THREE.Vector3(...b), direction=B.clone().sub(A);
    const m=new THREE.Mesh(new THREE.CylinderGeometry(r2,r1,direction.length(),16),material);
    m.position.copy(A).add(B).multiplyScalar(.5);
    m.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),direction.normalize()); stageGroup.add(m);
    return m;
  };
  for(let i=0;i<3;++i) {
    const a=i*2*Math.PI/3+.4, x=1.97*Math.sin(a), z=1.97*Math.cos(a);
    rod([0,1.73,0],[x,.14,z],.095,.075,dark);
    rod([0,.53,0],[x*.70,.56,z*.70],.038,.035,silver);
    rod([x,.03,z],[x,.15,z],.16,.14,dark);
  }
  rod([0,.37,0],[0,2.75,0],.125,.09,silver);
  rod([0,1.52,0],[0,1.86,0],.20,.17,dark);
  rod([0,2.59,0],[0,2.76,0],.20,.20,mint);
  const stem=rod([0,2.7,0],[0,2.89,0],.088,.088,silver);
  pivot.position.y=2.87; pivot.rotation.order='YXZ';
  let disposed=false, model=null, visible=true, angle=.66, elevation=.32, radius=8.05, cameraMode='isometric';
  let drag=null, lastPose={roll:0,pitch:0,yaw:0}, elapsed=0, washEnabled=true;
  const assets=new Map();
  async function asset(name) {
    const url=new URL('../assembly/'+name.replace(/^\.\//,''),import.meta.url).href;
    if(!assets.has(url)) assets.set(url,loadGLB(url));
    return (await assets.get(url)).clone(true);
  }
  const rings=MOTOR_LAYOUT.map(({x,z})=>{
    const trail=new THREE.Group();trail.position.set(x*.39,-.14,z*.39);
    const material=new THREE.MeshBasicMaterial({color:0x66d6ca,transparent:true,opacity:0,depthWrite:false});
    for(let i=0;i<3;i++) {
      const ring=new THREE.Mesh(new THREE.TorusGeometry(.39,.012,4,24),material);
      ring.rotation.x=-Math.PI/2; trail.add(ring);
    }
    pivot.add(trail); return trail;
  });
  onStatus('Loading F450 model');
  loadAssemblyTripod(THREE,asset).then(assembly=>{
    if(disposed) { disposeTree(assembly.root); return; }
    model=assembly; pivot.add(model.root);
    onStatus(model.loaded===model.total?'':('Model parts loaded '+model.loaded+'/'+model.total));
  }).catch(()=>{if(!disposed)onStatus('3D model unavailable');});
  function resize(){
    const w=stage.clientWidth,h=stage.clientHeight;
    if(!w||!h)return;
    camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h,false);
  }
  const observer=new ResizeObserver(resize);observer.observe(stage);resize();
  canvas.addEventListener('pointerdown',e=>{
    if(e.button!==0)return;
    canvas.setPointerCapture(e.pointerId); drag={id:e.pointerId,x:e.clientX,y:e.clientY,pose:{...lastPose}};
  },{signal});
  canvas.addEventListener('pointermove',e=>{
    if(!drag || e.pointerId!==drag.id)return;
    const dx=e.clientX-drag.x,dy=e.clientY-drag.y;
    if (onDisturb?.(drag.pose.roll+dx*.16,drag.pose.pitch-dy*.16)) return;
    cameraMode='manual'; angle-=dx*.008; elevation=THREE.MathUtils.clamp(elevation+dy*.007,-.12,1.49);
    drag.x=e.clientX;drag.y=e.clientY;
  },{signal});
  for(const name of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(name,e=>{
    if(drag?.id===e.pointerId)drag=null;
  },{signal});
  canvas.addEventListener('wheel',e=>{
    if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();radius=THREE.MathUtils.clamp(radius+e.deltaY*.017,4.9,13);
  },{passive:false,signal});
  return {
    view(name) { cameraMode=name;[angle,elevation]=views[name]||views.isometric; },
    wash(enabled) {washEnabled=enabled;},
    draw(pose, simulation, dt) {
      if(disposed)return;
      elapsed+=dt; visible=!!pose;
      if(pose)lastPose=pose;
      pivot.visible=visible;
      if(visible)pivot.rotation.set((lastPose.pitch||0)*rad,(lastPose.yaw||0)*rad,-(lastPose.roll||0)*rad,'YXZ');
      const travel=simulation?.vertical.z??0;
      pivot.position.y=2.87+travel*7;
      stem.position.y=2.795+travel*3.5;stem.scale.y=1+travel*7/.19;
      for(let i=0;i<4;i++){
        const rpm=simulation?.running?simulation.motorRPM[i]:0, power=rpm/8500;
        if(model){
          model.propGroups[i].rotation.y-=MOTOR_LAYOUT[i].spin*dt*rpm*Math.PI/30;
          model.blurs[i].material.opacity=Math.min(.45,power*.5);
        }
        const trail=rings[i]; trail.visible=washEnabled&&power>.08;
        if(!trail.visible)continue;
        trail.children[0].material.opacity=Math.min(.34,power*.45);
        trail.children.forEach((ring,j)=>{
          const phase=(elapsed*power*1.8+j/3)%1;
          ring.position.y=-phase*1.65;ring.scale.setScalar(.85+phase*.72);
        });
      }
      const yaw=cameraMode==='follow'?(lastPose.yaw||0)*rad:0;
      const orbit=angle+yaw;
      // Frame the whole stand even when the column narrows to a phone screen.
      const distance=radius*Math.max(1,.85/camera.aspect);
      camera.position.set(Math.sin(orbit)*distance*Math.cos(elevation),1.76+Math.sin(elevation)*distance,Math.cos(orbit)*distance*Math.cos(elevation));
      camera.lookAt(0,1.76,0);renderer.render(scene,camera);
    },
    dispose(){disposed=true;observer.disconnect();disposeTree(scene);renderer.dispose();renderer.forceContextLoss?.();canvas.remove();assets.clear();}
  };
}
