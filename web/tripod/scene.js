import * as THREE from '../assembly/three.module.min.js';
import {loadGLB} from '../assembly/glb-loader.js';
import {CanvasRenderer} from '../assembly/js/canvas-renderer.js';
import {loadAssemblyTripod, MOTOR_LAYOUT} from './tripod-assembly-model.js';

const rad = Math.PI/180;
const views = {isometric:[.66,.4], rear:[0,.36], front:[Math.PI,.3], left:[-Math.PI/2,.28], right:[Math.PI/2,.28], top:[0,1.49], follow:[0,.36]};
// The exported F450 has a +Z nose. In the pilot view, right is +X and forward is -Z.
export function setPilotAttitude(rotation, pose) {
  rotation.set(-(pose.pitch??0)*rad,-(pose.yaw??0)*rad,-(pose.roll??0)*rad,'YXZ');
}
function disposeTree(group) {
  const geometries=new Set(), materials=new Set();
  group.traverse(part=>{
    if (part.geometry) geometries.add(part.geometry);
    for (const material of [part.material].flat()) if (material) materials.add(material);
  });
  geometries.forEach(g=>g.dispose()); materials.forEach(m=>m.dispose());
}
export function createScene(stage, onStatus, onDisturb, signal, onOrbit=()=>{}) {
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
  const airframe=new THREE.Group(); airframe.scale.z=-1; pivot.add(airframe);
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
  const feet=[];
  for(let i=0;i<3;++i) {
    const a=i*2*Math.PI/3+.4, x=1.97*Math.sin(a), z=1.97*Math.cos(a);
    feet.push(new THREE.Vector3(x,.1,z));
    rod([0,1.73,0],[x,.14,z],.095,.075,dark);
    rod([0,.53,0],[x*.70,.56,z*.70],.038,.035,silver);
    rod([x,.03,z],[x,.15,z],.16,.14,dark);
  }
  rod([0,.37,0],[0,2.75,0],.125,.09,silver);
  rod([0,1.52,0],[0,1.86,0],.20,.17,dark);
  rod([0,2.59,0],[0,2.76,0],.20,.20,mint);
  const stem=rod([0,2.7,0],[0,2.89,0],.088,.088,silver);
  pivot.position.y=2.87; pivot.rotation.order='YXZ';
  let disposed=false, model=null, visible=true, angle=views.rear[0], elevation=views.rear[1], zoom=1, cameraMode='rear';
  let targetAngle=angle,targetElevation=elevation;
  let drag=null, lastPose={roll:0,pitch:0,yaw:0}, intensity=1;
  const reduced=window.matchMedia('(prefers-reduced-motion: reduce)');
  const assets=new Map();
  async function asset(name) {
    const url=new URL('../assembly/'+name.replace(/^\.\//,''),import.meta.url).href;
    if(!assets.has(url)) assets.set(url,loadGLB(url));
    return (await assets.get(url)).clone(true);
  }
  const phases=[0,0,0,0], down=new THREE.Vector3(), hub=new THREE.Vector3();
  const rotorCenters=MOTOR_LAYOUT.map(m=>new THREE.Vector3(m.x*.39,.47,-m.z*.39));
  const viewDirection=new THREE.Vector3(),screenRight=new THREE.Vector3(),screenUp=new THREE.Vector3();
  const offset=new THREE.Vector3(),center=new THREE.Vector3(),halfFov=Math.tan(camera.fov*rad/2);
  const floorGeometry=new THREE.RingGeometry(.57,.60,32);
  const floorRings=[],motorLights=[];
  const dustCount=soft?0:96, dustPositions=new Float32Array(dustCount*3);
  const dustGeo=new THREE.BufferGeometry();
  dustGeo.setAttribute('position',new THREE.BufferAttribute(dustPositions,3));
  const dust=new THREE.Points(dustGeo,new THREE.PointsMaterial({size:.026,color:0x99dacd,transparent:true,opacity:.28,depthWrite:false}));
  dust.frustumCulled=false;dust.visible=false;scene.add(dust);
  const rings=MOTOR_LAYOUT.map(({x,z},i)=>{
    const trail=new THREE.Group();trail.position.set(x*.39,-.14,z*.39);
    const material=new THREE.MeshBasicMaterial({color:0x66d6ca,transparent:true,opacity:0,depthWrite:false});
    for(let i=0;i<3;i++) {
      const ring=new THREE.Mesh(new THREE.TorusGeometry(.39,.012,4,24),material);
      ring.rotation.x=-Math.PI/2; trail.add(ring);
    }
    airframe.add(trail);
    const light=new THREE.Mesh(new THREE.TorusGeometry(.10,.015,5,24),new THREE.MeshBasicMaterial({color:i<2?0xff896c:0x78dace,depthWrite:false,transparent:true,opacity:0}));
    light.rotation.x=Math.PI/2;light.position.set(x*.39,.47,z*.39);airframe.add(light);motorLights.push(light);
    const floor=new THREE.Mesh(floorGeometry,new THREE.MeshBasicMaterial({color:0x78cbb7,transparent:true,opacity:0,depthWrite:false,side:THREE.DoubleSide}));
    floor.rotation.x=-Math.PI/2;floor.visible=false;stageGroup.add(floor);floorRings.push(floor);
    return trail;
  });
  onStatus('Loading F450 model');
  loadAssemblyTripod(THREE,asset).then(assembly=>{
    if(disposed) { disposeTree(assembly.root); return; }
    model=assembly; airframe.add(model.root);
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
    if(cameraMode!=='manual'){cameraMode='manual';targetAngle=angle;targetElevation=elevation;onOrbit();}
    targetAngle-=dx*.008;targetElevation=THREE.MathUtils.clamp(targetElevation+dy*.007,-.12,1.49);
    drag.x=e.clientX;drag.y=e.clientY;
  },{signal});
  for(const name of ['pointerup','pointercancel','lostpointercapture'])canvas.addEventListener(name,e=>{
    if(drag?.id===e.pointerId)drag=null;
  },{signal});
  canvas.addEventListener('wheel',e=>{
    if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();zoom=THREE.MathUtils.clamp(zoom+e.deltaY*.0014,.63,1.7);
  },{passive:false,signal});
  return {
    view(name) {if(views[name]){cameraMode=name;[targetAngle,targetElevation]=views[name];}},
    wash(level) {intensity=level==='off'?0:level==='soft'?.42:1;},
    draw(pose, simulation, dt) {
      if(disposed)return;
      visible=!!pose;
      if(pose)lastPose=pose;
      pivot.visible=visible;
      if(visible)setPilotAttitude(pivot.rotation,lastPose);
      const travel=simulation?.vertical.z??0;
      pivot.position.y=2.87+travel*7;
      stem.position.y=2.795+travel*3.5;stem.scale.y=1+travel*7/.19;
      pivot.updateWorldMatrix(true,false);
      down.set(0,-1,0).applyQuaternion(pivot.quaternion);
      dust.visible=dustCount>0 && !reduced.matches && intensity>0 && !!simulation?.running;
      for(let i=0;i<4;i++){
        const rpm=simulation?.running?simulation.motorRPM[i]:0, power=rpm/8500;
        if(model){
          model.propGroups[i].rotation.y+=MOTOR_LAYOUT[i].spin*dt*rpm*Math.PI/30;
          model.blurs[i].material.opacity=Math.min(.45,power*.5);
        }
        const trail=rings[i],floor=floorRings[i];
        motorLights[i].material.opacity=Math.min(.8,power*.95);
        phases[i]=(phases[i]+dt*power*1.8)%1;
        trail.visible=intensity>0 && power>.08;floor.visible=trail.visible;
        if(dust.visible || floor.visible){
          trail.getWorldPosition(hub);
          const fall=hub.y/Math.max(.12,-down.y);
          floor.position.set(hub.x+fall*down.x,.045,hub.z+fall*down.z);
          floor.scale.setScalar(.65+power*.7+(reduced.matches?0:phases[i]*.46));
          floor.material.opacity=.30*power*intensity*(reduced.matches?1:1-phases[i]);
          if(dust.visible){
            for(let j=i;j<dustCount;j+=4){
              const phase=(phases[i]+j*.618)%1,theta=j*2.4,r=.18+phase*(.4+power);
              dustPositions[3*j]=floor.position.x+r*Math.cos(theta);
              dustPositions[3*j+2]=floor.position.z+r*Math.sin(theta);
              dustPositions[3*j+1]=power>.08?.055+.24*Math.sin(phase*Math.PI)*power:-10;
            }
          }
        }
        if(!trail.visible)continue;
        trail.children[0].material.opacity=Math.min(.34,power*.45)*intensity;
        trail.children.forEach((ring,j)=>{
          const phase=((reduced.matches?0:phases[i])+j/3)%1;
          ring.position.y=-phase*1.65;ring.scale.setScalar(.85+phase*.72);
        });
      }
      if(dust.visible){dustGeo.attributes.position.needsUpdate=true;dust.material.opacity=.30*intensity;}
      const yaw=cameraMode==='follow'?-(lastPose.yaw||0)*rad:0;
      const blend=reduced.matches?1:1-Math.exp(-Math.max(0,dt)*12);
      const delta=targetAngle+yaw-angle;
      angle+=Math.atan2(Math.sin(delta),Math.cos(delta))*blend;
      elevation+=(targetElevation-elevation)*blend;
      const orbit=angle;
      viewDirection.set(Math.sin(orbit)*Math.cos(elevation),Math.sin(elevation),Math.cos(orbit)*Math.cos(elevation));
      screenRight.set(Math.cos(orbit),0,-Math.sin(orbit));
      screenUp.crossVectors(viewDirection,screenRight);
      center.set(0,1.82+travel*3.5,0);
      // Fit the rotor guards and the feet at the current tilt (including perspective).
      let fit=5.4;
      const include=(point,padding)=>{
        offset.copy(point).sub(center);
        const height=(Math.abs(offset.dot(screenUp))+padding)/halfFov;
        const width=(Math.abs(offset.dot(screenRight))+padding)/(halfFov*camera.aspect);
        fit=Math.max(fit,offset.dot(viewDirection)+padding+Math.max(width,height)*1.1);
      };
      for(const foot of feet)include(foot,.17);
      for(const rotor of rotorCenters)include(hub.copy(rotor).applyMatrix4(pivot.matrixWorld),.67);
      camera.position.copy(center).addScaledVector(viewDirection,fit*zoom);
      camera.lookAt(center);renderer.render(scene,camera);
    },
    dispose(){disposed=true;observer.disconnect();disposeTree(scene);renderer.dispose();renderer.forceContextLoss?.();canvas.remove();assets.clear();}
  };
}
