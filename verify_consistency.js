// 一致性檢查 v2（2026-08-09 減法重構）：
//   舊版驗「頁面 JS 現算 vs Python BASE_PENDING vs 覆蓋度卡」三方一致——JS 生成層已於減法重構移除，
//   新版改驗：(a) 三頁 script 於 vm 零錯誤（init + 各 render tab）
//            (b) renderPick 輸出包含 BASE_PENDING 的全部號碼（頁面顯示 == 事前發布）
//            (c) BASE_PENDING 為 v2 時做結構驗規：12碼不重複、避上期、每組 max≥hi、無等差、無同尾、號域覆蓋
//            (d) --recompute 時另呼叫 pick_engine.py 重算比對（頁面顯示 == Python 發布 == 規格重算）
// 用法：node ~/539/verify_consistency.js [--new] [--recompute]
//   --new       驗 *.html.new（手術後、覆蓋前的預檢）
//   --recompute 加跑 Python 重算比對（Phase 4 起的完整三方一致）
// 每次改頁面或改 pick_engine 後必跑，全綠才可 push。

const fs=require('fs'), vm=require('vm'), cp=require('child_process');
const dir=process.env.HOME+'/539/';
const useNew=process.argv.includes('--new');
const recompute=process.argv.includes('--recompute');
let allOk=true;

const GAMES={ '539':{pool:39,zones:[0,1,2,3]}, 'f5':{pool:39,zones:[0,1,2,3]}, 'm6':{pool:49,zones:[0,1,2,3,4]} };

function structCheck(game,pending,lastDraw){
  const errs=[];
  if(!pending) return ['無 BASE_PENDING'];
  if(pending.v!==2) return null;                    // 舊格式：跳過結構驗規（相容期）
  const zs=GAMES[game].zones, zone=n=>Math.floor(n/10);
  const gs=Object.entries(pending.strategies||{});
  const flat=gs.flatMap(([,g])=>g);
  if(gs.length!==4) errs.push(`組數 ${gs.length}≠4`);
  if(flat.length!==12||new Set(flat).size!==12) errs.push('12碼有重複');
  if(flat.some(n=>lastDraw.includes(n))) errs.push('含上期號碼');
  for(const [k,g] of gs){
    if(g.length!==3){errs.push(`${k} 非3碼`);continue;}
    const [a,b,c]=g;
    if(!(a<b&&b<c)) errs.push(`${k} 未升冪`);
    if(c<pending.hi) errs.push(`${k} 違反R1(max<${pending.hi})`);
    if(b-a===c-b) errs.push(`${k} 等差`);
    if(a%10===b%10&&b%10===c%10) errs.push(`${k} 同尾`);
    if(!(pending.relaxed||[]).includes('zone')&&zone(a)===zone(b)&&zone(b)===zone(c)) errs.push(`${k} 同號域`);
  }
  if(!(pending.relaxed||[]).includes('cover')){
    const cov=new Set(flat.map(zone));
    if(zs.some(z=>!cov.has(z))) errs.push('號域未全覆蓋');
  }
  // fpx-v1 排除區（2026-08-12）：sfg-v2 選號必須與有效排除區不相交
  if(pending.exclAlgo==='fpx-v1'){
    const ex=pending.excluded||[];
    if(new Set(ex).size!==ex.length) errs.push('排除區有重複');
    if(ex.some((n,i)=>i&&ex[i-1]>=n)) errs.push('排除區未升冪');
    if(ex.some(n=>n<1||n>GAMES[game].pool)) errs.push('排除區超出號池');
    const hitEx=flat.filter(n=>ex.includes(n));
    if(hitEx.length) errs.push(`選號含排除區 ${hitEx}`);
    if(!Array.isArray(pending.exclDepths)) errs.push('缺 exclDepths');
  }
  return errs;
}

function check(game,dataFile,htmlFile,label){
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
  const htmlPath=dir+htmlFile+(useNew?'.new':'');
  for(const m of fs.readFileSync(htmlPath,'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)){
    try{ vm.runInContext(m[1],sandbox); }catch(e){ errs.push('parse:'+e.message); }
  }
  const out=vm.runInContext(`
    (function(){
      const errs=[];
      try{ if(typeof init==='function') init(); }catch(e){ errs.push('init:'+e.message); }
      // renderPick 輸出攔截：驗「顯示 == 發布」
      let pickHTML='';
      const recEl={ set innerHTML(v){ pickHTML=String(v); }, get innerHTML(){ return pickHTML; } };
      try{ renderPick(recEl); }catch(e){ errs.push('renderPick:'+e.message); }
      for(const fn of ['renderTrack','renderReport','renderAnnual','renderStats','renderRecords','renderSettings','renderCompanion']){
        try{ if(typeof this[fn]==='function'||typeof eval(fn)==='function') eval(fn)(__mkEl()); }catch(e){ errs.push(fn+':'+e.message); }
      }
      const pend=BASE_PENDING||null;
      let missing=[];
      if(pend&&pend.strategies){
        const f2=n=>String(n).padStart(2,'0');
        for(const nums of Object.values(pend.strategies))
          for(const n of nums) if(!pickHTML.includes('>'+f2(n)+'<')) missing.push(n);
      }
      return JSON.stringify({errs, missing, pend, lastDraw:(typeof BASE_REC!=='undefined'&&BASE_REC[0])?BASE_REC[0].n:[]});
    })()
  `,sandbox);
  const r=JSON.parse(out);
  errs=errs.concat(r.errs);
  const struct=structCheck(game,r.pend,r.lastDraw);
  const parts=[];
  parts.push(errs.length?`❌ 腳本錯誤:${errs.join('|')}`:'✅ 腳本零錯誤');
  parts.push(r.missing.length?`❌ 顯示缺號:${r.missing.join(',')}`:'✅ 顯示=發布');
  if(struct===null) parts.push('ℹ️ 舊格式 pending（相容期，跳過結構驗規）');
  else parts.push(struct.length?`❌ 結構:${struct.join('|')}`:'✅ v2 結構合規');
  let recompOk=null;
  if(recompute&&r.pend&&r.pend.v===2){
    try{
      // sfg-v2 起用 auto 模式（讀同一份 data 檔重算排除區＋四組）——完整三方一致
      const py=cp.execFileSync('/usr/bin/python3',[dir+'pick_engine.py',game],{encoding:'utf8'});
      const got={};
      for(const m of py.matchAll(/^\s+([A-D]): \[([\d, ]+)\]/gm)) got[m[1]]=m[2].split(',').map(s=>+s.trim());
      const mEx=py.match(/^\s+EXCL: \[([\d, ]*)\]/m);
      const gotEx=mEx&&mEx[1].trim()?mEx[1].split(',').map(s=>+s.trim()):[];
      const groupsOk=JSON.stringify(got)===JSON.stringify(r.pend.strategies);
      const exOk=r.pend.exclAlgo!=='fpx-v1'||JSON.stringify(gotEx)===JSON.stringify(r.pend.excluded||[]);
      recompOk=groupsOk&&exOk;
      parts.push(recompOk?'✅ Python重算一致(組+排除區)':'❌ Python重算不一致 '+(groupsOk?'':'組 ')+(exOk?'':'排除區'));
    }catch(e){ parts.push('❌ 重算失敗:'+e.message.slice(0,80)); recompOk=false; }
  }
  const ok=!errs.length&&!r.missing.length&&(struct===null||!struct.length)&&(recompOk!==false);
  if(!ok) allOk=false;
  console.log(`${label}: ${parts.join(' | ')}`);
}

check('539','data_539.js','index.html','539');
check('f5','data_f5.js','fantasy5.html','F5 ');
check('m6','data_m6.js','marksix.html','M6 ');
console.log(allOk?'VERIFY PASS ✅':'VERIFY FAIL ❌');
process.exit(allOk?0:1);
