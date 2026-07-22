// 一致性檢查（2026-07-22）：驗證三系統「選號頁 JS 現算」vs「Python BASE_PENDING」vs「覆蓋度卡前10碼」三方一致
// 用法：node ~/539/verify_consistency.js —— 每次新增/修改策略或改頁面後必跑，全綠才可 push

const fs=require('fs'), vm=require('vm');
const dir=process.env.HOME+'/539/';
function check(dataFile, htmlFile, label){
  const mkEl=()=>new Proxy(function(){}, {
    get(t,p){ if(p==='style'||p==='dataset') return new Proxy({},{get:()=>'',set:()=>true});
      if(p==='classList') return {add(){},remove(){},toggle(){},contains:()=>false};
      if(p==='children'||p==='childNodes') return [];
      if(p===Symbol.toPrimitive) return ()=>'';
      if(p==='innerHTML'||p==='textContent'||p==='value'||p==='id') return '';
      return typeof p==='symbol' ? undefined : mkEl(); },
    set(){return true}, apply(){return mkEl()}
  });
  const store={};
  const documentProxy=new Proxy({},{get(t,p){
    if(p==='getElementById'||p==='querySelector'||p==='createElement') return ()=>mkEl();
    if(p==='querySelectorAll') return ()=>[];
    if(p==='addEventListener') return ()=>{};
    if(p==='body'||p==='documentElement'||p==='head') return mkEl();
    return ()=>mkEl();
  }});
  const sandbox={console,JSON,Math,Object,Array,Set,Map,Number,String,Boolean,parseInt,parseFloat,isNaN,isFinite,RegExp,Error,Promise,Symbol,Date,
    localStorage:{getItem:k=>store[k]??null,setItem:(k,v)=>{store[k]=String(v)},removeItem:k=>{delete store[k]}},
    document:documentProxy, alert:()=>{}, confirm:()=>true, prompt:()=>null,
    navigator:{clipboard:{writeText:()=>Promise.resolve()}}, location:{search:'',hash:'',href:''},
    addEventListener:()=>{}, removeEventListener:()=>{}, setTimeout:()=>0, setInterval:()=>0, clearTimeout:()=>{}, clearInterval:()=>{},
    requestAnimationFrame:()=>0, fetch:()=>Promise.resolve({ok:false,json:()=>Promise.resolve({})}), matchMedia:()=>({matches:false,addListener(){},addEventListener(){}})};
  sandbox.window=sandbox; sandbox.globalThis=sandbox; sandbox.__mkEl=mkEl;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(dir+dataFile,'utf8'),sandbox);
  let errs=[];
  for(const m of fs.readFileSync(dir+htmlFile,'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)){
    try{ vm.runInContext(m[1],sandbox); }catch(e){ errs.push(e.message); }
  }
  const out=vm.runInContext(`
    (function(){
      const errs=[];
      try{ if(typeof init==='function') init(); }catch(e){ errs.push('init:'+e.message); }
      try{ renderPick(__mkEl()); }catch(e){ errs.push('renderPick:'+e.message); }
      const g=allGroups();
      const cnt={};
      for(const [k,v] of Object.entries(g)){
        if(k==='cand'||k==='gc'||!v||!v.nums) continue;
        v.nums.forEach(n=>cnt[n]=(cnt[n]||0)+1);
      }
      const g0=genG0(); if(g0) g0.forEach(n=>cnt[n]=(cnt[n]||0)+1);
      const cardTop10=Object.entries(cnt).sort((a,b)=>b[1]-a[1]||(+a[0])-(+b[0])).slice(0,10).map(([n])=>+n);
      return JSON.stringify({errs, cardTop10, gc:g.gc.nums, pyGC:(BASE_PENDING.strategies||{}).GC||null});
    })()
  `,sandbox);
  const r=JSON.parse(out);
  errs=errs.concat(r.errs);
  const same=JSON.stringify(r.cardTop10)===JSON.stringify(r.gc);
  const pyOk=JSON.stringify(r.gc)===JSON.stringify(r.pyGC);
  console.log(`${label}: 卡片前10 ${same?'✅=GC':'❌≠GC'} | JS-GC vs Py-pending ${pyOk?'✅一致':'❌不同 '+JSON.stringify(r.pyGC)} | ${JSON.stringify(r.gc)}${errs.length?' ⚠️ '+errs.join('|'):''}`);
}
check('data_539.js','index.html','539');
check('data_f5.js','fantasy5.html','F5');
check('data_m6.js','marksix.html','M6');
