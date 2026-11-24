import {equal} from './config-commands.js';

const savedGroups=[134,4,7,112];
const restartKey=kit=>'areion.restart.checked.'+kit;

export class SetupProgress {
  constructor(){this.reset();}
  reset(){
    this.request?.abort();this.request=null;this.nextRead=0;
    this.connection=null;this.kit=null;this.boot=null;this.saved=new Map();this.queried=new Set();
    this.generation=(this.generation||0)+1;this.loading=false;this.restart=null;
  }
  interrupt(){
    this.request?.abort();this.nextRead=performance.now()+750;
  }
  invalidate(){
    this.interrupt();
    this.generation++;this.loading=false;this.queried.clear();this.saved.clear();
  }
  verifiedRestart(revision){
    this.restart=[this.boot,revision];
    try{sessionStorage.setItem(restartKey(this.kit),JSON.stringify(this.restart));}catch{/* current view */}
  }
  observe(ctx,setup,busy){
    if(ctx.replay || ctx.state!=='connected' || !ctx.link?.session || !setup?.[15])return;
    if(this.connection!==ctx.link || this.kit!==setup[15] || this.boot!==ctx.link.fcSession){
      this.reset();this.connection=ctx.link;this.kit=setup[15];this.boot=ctx.link.fcSession;
      try{this.restart=JSON.parse(sessionStorage.getItem(restartKey(this.kit)));}catch{/* current view */}
    }
    if(busy||this.loading||performance.now()<this.nextRead||!ctx.link.readGroup)return;
    const group=savedGroups.find(id=>!this.queried.has(id) && ctx.group(id));
    if(!group)return;
    const generation=this.generation,request=new AbortController();
    this.loading=true;this.request=request;this.queried.add(group);
    ctx.link.readGroup(group,{saved:true,signal:request.signal}).then(values=>{
      if(this.generation===generation)this.saved.set(group,values);
     }).catch(error=>{
      if(this.generation===generation && (request.signal.aborted || error.code==='BUSY')){
        this.queried.delete(group);this.nextRead=performance.now()+750;
      }
    }).finally(()=>{if(this.request===request){this.request=null;this.loading=false;}});
  }
  steps(ctx,setup,confirmed,locked,accPending){
    if(ctx.state!=='connected'||ctx.replay||!setup?.[15]||setup[15]!==this.kit||ctx.link!==this.connection||ctx.link.fcSession!==this.boot)
      return Array(10).fill('');
    const complete=setup[1]&&!setup[0], cfg=ctx.group(134), saved=this.saved.get(134);
    const field=i=>cfg&&saved&&cfg[i]===saved[i];
    const stored=g=>equal(ctx.group(g),this.saved.get(g));
    return [confirmed&&(locked||complete)?'Confirmed':'',
      field(0)||complete?'Profile saved':'',field(1)||complete?'Input saved':'',
      setup[5]&&!accPending?'ACC verified':'',cfg&&cfg[1]!==0?'Not used':setup[6]?'Receiver verified':'',
      setup[3]===4?'ESC verified':setup[3]===5?'Skipped':'',setup[4]===15?'Four outputs verified':'',
      complete||[4,7,112].every(stored)?'Settings saved':'',complete?'Saved on kit':'',
      complete&&this.restart?.[0]===this.boot&&this.restart[1]===setup[13]?'Restart verified':''];
  }
}
