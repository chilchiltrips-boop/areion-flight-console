// Project the same Three.js meshes and camera used by the WebGL workbench when
// a browser or graphics driver cannot supply a WebGL 2 context.
export class CanvasRenderer {
  constructor(THREE) {
    this.THREE = THREE;
    this.domElement = document.createElement('canvas');
    this.context = this.domElement.getContext('2d', {alpha:false});
    if (!this.context) throw new Error('This browser could not open a drawing canvas.');
    this.isCanvasRenderer = true;
    this.domElement.setAttribute('aria-label','Interactive 3D F450 assembly, software rendering');
    this.pixelRatio = 1;
    this.clip = new THREE.Matrix4();
    this.modelClip = new THREE.Matrix4();
    this.worldPoint = new THREE.Vector3();
    this.point = new THREE.Vector3();
    this.rgb = new THREE.Color();
    this.faces = [];
    this.projected = new Float32Array(0);
    this.nextFrame = 0;
    this.lastClip = new THREE.Matrix4();
    this.entries = [];
    this.needsPaint = true;
  }

  setPixelRatio(value) { this.pixelRatio = Math.min(value,1.5); }
  setSize(w,h,updateStyle=true) {
    this.width=w; this.height=h;
    this.domElement.width=Math.round(w*this.pixelRatio);
    this.domElement.height=Math.round(h*this.pixelRatio);
    if (updateStyle) {
      this.domElement.style.width=w+'px';
      this.domElement.style.height=h+'px';
    }
    this.context.setTransform(this.pixelRatio,0,0,this.pixelRatio,0,0);
    this.nextFrame=0;
    this.needsPaint=true;
  }

  // The table itself is flat. Paint its rings underneath the depth-sorted
  // parts so they stay continuous at the bench and camera boundaries.
  drawBench() {
    const g=this.context, segments=80;
    const pathPoint=(x,y,z,first)=>{
      const p=this.worldPoint.set(x,y,z).applyMatrix4(this.clip);
      const sx=(p.x+1)*this.width*.5, sy=(1-p.y)*this.height*.5;
      if(first)g.moveTo(sx,sy);else g.lineTo(sx,sy);
    };
    const ring=(r,y)=>{
      g.beginPath();
      for(let i=0;i<=segments;i++){
        const angle=i/segments*Math.PI*2;
        pathPoint(r*Math.cos(angle),y,r*Math.sin(angle),i===0);
      }
      g.closePath();
    };
    ring(6.7,-.32); g.fillStyle='#263740';g.fill();
    ring(6.7,.01); g.fillStyle='#253944';g.fill();
    ring(6.48,.025); g.fillStyle='#192d38';g.fill();
    g.strokeStyle='#31515f';g.lineWidth=.75;
    for(const r of [1.25,2.5,3.75,5,6.15]) {ring(r,.04);g.stroke();}
    g.beginPath();
    for(let i=0;i<16;i++) {
      const angle=i*Math.PI/8;
      pathPoint(0,.04,0,true);
      pathPoint(6.15*Math.cos(angle),.04,6.15*Math.sin(angle),false);
    }
    g.stroke();
  }

  mesh(object) {
    const geo=object.geometry, mat=object.material;
    if (!object.isMesh || !mat || mat.opacity<.02 || !mat.visible) return;
    const positions=geo.attributes.position;
    if (!positions) return;
    const colours=mat.vertexColors && geo.attributes.color, ids=geo.index;
    const coords=positions.count*3;
    if (this.projected.length<coords) this.projected=new Float32Array(coords);
    const buf=this.projected, w=this.width*.5, h=this.height*.5;
    this.modelClip.multiplyMatrices(this.clip,object.matrixWorld);
    for(let i=0;i<positions.count;i++) {
      const v=this.point.fromBufferAttribute(positions,i).applyMatrix4(this.modelClip);
      buf[3*i]=(v.x+1)*w; buf[3*i+1]=(1-v.y)*h; buf[3*i+2]=v.z;
    }
    const count=ids?.count??positions.count;
    for(let i=0;i+2<count;i+=3) {
      const ia=ids?ids.getX(i):i, ib=ids?ids.getX(i+1):i+1, ic=ids?ids.getX(i+2):i+2;
      const a=ia*3,b=ib*3,c=ic*3,az=buf[a+2],bz=buf[b+2],cz=buf[c+2];
      if(Math.min(az,bz,cz)<-1 || Math.max(az,bz,cz)>1)continue;
      const ax=buf[a],ay=buf[a+1],bx=buf[b],by=buf[b+1],cx=buf[c],cy=buf[c+1];
      if(Math.max(ax,bx,cx)<0 || Math.max(ay,by,cy)<0 || Math.min(ax,bx,cx)>w*2 || Math.min(ay,by,cy)>h*2)continue;
      const area=(bx-ax)*(cy-ay)-(by-ay)*(cx-ax);
      if(Math.abs(area)<.28 || (mat.side===this.THREE.FrontSide&&area>0) || (mat.side===this.THREE.BackSide&&area<0))continue;
      this.rgb.copy(mat.color);
      if(colours) {
        this.rgb.r*=colours.getX(ia); this.rgb.g*=colours.getY(ia); this.rgb.b*=colours.getZ(ia);
      }
      if(!mat.isMeshBasicMaterial && geo.attributes.normal) {
        this.point.fromBufferAttribute(geo.attributes.normal,ia).transformDirection(object.matrixWorld);
        this.rgb.multiplyScalar(.58+.56*Math.max(0,this.point.x*.34+this.point.y*.85+this.point.z*.38));
      }
      if(mat.emissive) {
        this.rgb.r+=mat.emissive.r*mat.emissiveIntensity;
        this.rgb.g+=mat.emissive.g*mat.emissiveIntensity;
        this.rgb.b+=mat.emissive.b*mat.emissiveIntensity;
      }
      this.faces.push({ax,ay,bx,by,cx,cy,depth:az+bz+cz,fill:this.rgb.getStyle(),alpha:mat.opacity});
    }
  }

  render(scene,camera) {
    const now=performance.now();
    if (now<this.nextFrame || document.hidden) return;
    const start=now;
    camera.updateMatrixWorld();
    scene.updateMatrixWorld();
    this.clip.multiplyMatrices(camera.projectionMatrix,camera.matrixWorldInverse);
    // Keep the previous image when the camera and visible meshes are static.
    // Compare in traversal order to catch deletion, undo and part replacement.
    let changed=this.needsPaint||!this.lastClip.equals(this.clip), count=0;
    for (const node of scene.children) {
      if(!node.isGroup && !node.userData.snapPreview)continue;
      node.traverseVisible(obj=>{
        const mat=obj.material;
        if(!obj.isMesh||!mat?.visible||mat.opacity<.02)return;
        let entry=this.entries[count++];
        if(!entry) {
          entry={matrix:new this.THREE.Matrix4()};
          this.entries.push(entry);
        }
        const color=mat.color?.getHex(), glow=mat.emissive?.getHex();
        if(entry.object!==obj || !entry.matrix.equals(obj.matrixWorld) ||
           entry.material!==mat || entry.geometry!==obj.geometry ||
           entry.opacity!==mat.opacity || entry.color!==color || entry.glow!==glow ||
           entry.intensity!==mat.emissiveIntensity) {
          entry.object=obj;entry.material=mat;entry.geometry=obj.geometry;
          entry.matrix.copy(obj.matrixWorld);entry.opacity=mat.opacity;
          entry.color=color;entry.glow=glow;entry.intensity=mat.emissiveIntensity;
          changed=true;
        }
      });
    }
    changed ||= this.entries.length!==count;
    this.entries.length=count;
    if(!changed) {this.nextFrame=now+40;return;}
    this.needsPaint=false;
    this.lastClip.copy(this.clip);
    const g=this.context;
    g.globalAlpha=1;g.fillStyle='#112431';g.fillRect(0,0,this.width,this.height);
    this.drawBench();
    this.faces.length=0;
    for(const entry of this.entries)this.mesh(entry.object);
    this.faces.sort((a,b)=>b.depth-a.depth);
    for(const f of this.faces) {
      g.globalAlpha=f.alpha;g.fillStyle=f.fill;g.beginPath();g.moveTo(f.ax,f.ay);
      g.lineTo(f.bx,f.by);g.lineTo(f.cx,f.cy);g.closePath();g.fill();
    }
    g.globalAlpha=1;
    this.nextFrame=performance.now()+Math.max(40,performance.now()-start);
  }
  dispose() {this.entries.length=0;this.faces.length=0;this.projected=new Float32Array(0);}
}
