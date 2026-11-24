// Host receipt time is in milliseconds. Plots share the telemetry clock with CSV playback.
const maxGap = 500;
const median = xs => {
  const ranked = xs.slice().sort((a,b) => a-b);
  const mid = ranked.length >>> 1;
  return ranked.length % 2 ? ranked[mid] : (ranked[mid-1] + ranked[mid]) / 2;
};

function firstAt(rows, at) {
  let low = 0, high = rows.length;
  while (low < high) {
    const mid = (low + high) >>> 1;
    if (rows[mid].at < at) low = mid + 1;
    else high = mid;
  }
  return low;
}

export function accepted(report, timeouts = [250,250]) {
  if (!report) return 0;
  const [source,active,ppm,ap,ready,count,age,owner,usb] = report;
  const signal = [ppm,ap,usb][source];
  if (!ready || !signal || active !== source+1 || age < 0 || age >= (timeouts?.[source ? 1 : 0] ?? 250)) return 0;
  if (source === 0) return count >= 4 && count <= 8 ? count : 0;
  return (source === 1 || source === 2) && count === 8 && owner ? count : 0;
}

// Rebuild evidence in packet arrival order, including validity transitions inside the window.
export function scopeHistory(rows, clock, seconds, timeouts) {
  const start = clock - seconds * 1000;
  const groups = new Map([[21,[]],[22,[]],[23,[]]]);
  let status, input, receiverKey = '', epoch = 0;
  for (let i = firstAt(rows, start-maxGap); i < rows.length; i++) {
    const row = rows[i];
    if (row.at > clock) break;
    if (row.group === 120) status = row;
    if (row.group === 112) timeouts = row.values;
    if (row.group === 122) {
      input = row;
      const v = row.values;
      const key = accepted(v,timeouts) ? [v[0],v[5],v[0] ? v[7] : 0].join('/') : '';
      if (key !== receiverKey) { epoch++; receiverKey = key; }
    }
    if (row.at < start || !groups.has(row.group)) continue;
    let count = row.values.length;
    if (row.group === 21 && (!status || !status.values[2] || !status.values[5] || row.at-status.at > maxGap)) count = 0;
    if (row.group === 22) count = input && row.at-input.at <= maxGap ? accepted(input.values,timeouts) : 0;
    groups.get(row.group).push({at:row.at, values:row.values, count, epoch:row.group === 22 ? epoch : 0});
  }
  return groups;
}

export function trace(samples, index) {
  const intervals = [];
  for (let i=1;i<samples.length;i++) if(samples[i].at > samples[i-1].at) intervals.push(samples[i].at-samples[i-1].at);
  const gap = intervals.length ? Math.min(maxGap,Math.max(35,3*median(intervals))) : maxGap;
  const segments = [];
  let line = null, previous;
  for (const sample of samples) {
    if (previous && (sample.at-previous.at>gap || sample.epoch!==previous.epoch)) line=null;
    if (index >= sample.count || !Number.isFinite(sample.values[index])) line=null;
    else {
      if (!line) { line=[]; segments.push(line); }
      line.push([sample.at,sample.values[index]]);
    }
    previous=sample;
  }
  return segments;
}

function amplitudes(input) {
  const n=input.length, real = new Float64Array(n), imag=new Float64Array(n);
  const mean=input.reduce((a,b)=>a+b,0)/n;
  let weightSum=0;
  for(let i=0,j=0;i<n;i++) {
    const w=.5-.5*Math.cos(2*Math.PI*i/n);
    weightSum+=w; real[j]=(input[i]-mean)*w;
    for(let mask=n>>1; mask; mask>>=1) { j^=mask; if(j&mask) break; }
  }
  for(let width=2;width<=n;width*=2){
    const half=width>>1;
    for(let k=0;k<half;k++) {
      const phi=-2*Math.PI*k/width, c=Math.cos(phi), s=Math.sin(phi);
      for(let a=k;a<n;a+=width) {
        const b=a+half, r=c*real[b]-s*imag[b], im=s*real[b]+c*imag[b];
        real[b]=real[a]-r; imag[b]=imag[a]-im; real[a]+=r; imag[a]+=im;
      }
    }
  }
  return Array.from({length:n/2},(_,i)=>Math.hypot(real[i+1],imag[i+1])*(i+1===n/2?1:2)/weightSum);
}

export function spectrum(samples, now, firmware) {
  const waiting = message => ({message});
  let start=samples.length;
  while(start && samples[start-1].count && (start===samples.length || (
    samples[start].at>samples[start-1].at && samples[start].at-samples[start-1].at<=maxGap))) start--;
  let rows=samples.slice(Math.max(start,samples.length-256));
  if (!rows.length || now-rows.at(-1).at > maxGap) return waiting('Waiting for current IMU telemetry');
  if (rows.length<32) return waiting('Collecting IMU samples · '+rows.length+'/32');
  const cadence=median(rows.slice(2).map((r,i)=>(r.at-rows[i].at)/2));
  let good=0;
  for(let i=1;i<rows.length;i++) {
    const dt=rows[i].at-rows[i-1].at;
    if (dt<.45*cadence || dt>1.65*cadence) good=i;
  }
  const n=2**Math.floor(Math.log2(rows.length-good));
  if(n<32) return waiting('Waiting for continuous IMU timing');
  rows=rows.slice(-n);
  const first=rows[0].at, period=(rows.at(-1).at-first)/(n-1), fs=1000/period;
  if(rows.some((row,i)=>Math.abs(row.at-first-i*period)>.95*period) ||
     (['3.1.0','3.2.0','3.3.0','3.4.0'].includes(firmware) && fs>2/.15*1.12))
    return waiting('Irregular telemetry timing');
  const grid=Array.from({length:6},()=>[]);
  let right=1;
  for(let i=0;i<n;i++) {
    const target=first+i*period;
    while(right<n-1 && rows[right].at<target) right++;
    const a=rows[right-1], b=rows[right], mix=Math.max(0,Math.min(1,(target-a.at)/(b.at-a.at)));
    for(let axis=0;axis<6;axis++) grid[axis].push(a.values[axis]+mix*(b.values[axis]-a.values[axis]));
  }
  return {fs,n,bins:grid.map(axis=>amplitudes(axis).map((v,i)=>[(i+1)*fs/n,v]))};
}
