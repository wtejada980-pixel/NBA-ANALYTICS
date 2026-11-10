'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'index.html'),'utf8');
const source=fs.readFileSync(path.join(root,'assets/v3-lab.js'),'utf8');
assert.match(html,/id="v3-lab-content"/);
assert.match(html,/assets\/v3-lab\.js/);
async function check(failure=false){
 const el={innerHTML:'',textContent:''};
 const future=new Date(Date.now()+86400000).toISOString();
 const earlier=new Date(Date.now()-3600000).toISOString();
 const data={
  'data/v3/evaluation.json':{segments:{test:{
   v3:{n:1316,winner_accuracy_pct:67.2,brier:.20938},
   v2_reconstructed_without_players:{n:1316,winner_accuracy_pct:66.9,brier:.2085},
   elo:{n:1316,winner_accuracy_pct:67.2,brier:.21358}}}},
  'data/v3/shadow.json':{prospective:{n:0,
   v2_original:{n:0,brier:null,winner_accuracy_pct:null},
   v3_shadow:{n:0,brier:null,winner_accuracy_pct:null}},
   forecasts:{'1':{predicted_at:earlier,scheduled_at:future,
    v2_original_home_pct:60,v3_home_pct:42}}},
  'data/latest.json':{games:[{id:'1',
   home:{name:'New York Knicks'},away:{name:'Boston Celtics'}}]}
 };
 const context={document:{getElementById:id=>id==='v3-lab-content'?el:null},
  Date,Intl,console,
  fetch:async url=>{
   if(failure)throw Error('network');
   const key=String(url).split('?')[0];
   if(!data[key])throw Error('unknown url '+key);
   return {ok:true,json:async()=>data[key]};
  }};
 vm.runInNewContext(source,context);
 await new Promise(r=>setTimeout(r,25));
 return el;
}
(async()=>{
 const el=await check();
 assert.match(el.innerHTML,/67\.2%/);
 assert.match(el.innerHTML,/66\.9%/);
 assert.match(el.innerHTML,/Brier 0\.20938/);
 assert.match(el.innerHTML,/New York Knicks 60\.0%/);
 assert.match(el.innerHTML,/Boston Celtics 58\.0%/);
 assert.match(el.innerHTML,/NO cuenta como éxito prospectivo/);
 const failed=await check(true);
 assert.match(failed.textContent,/no está disponible temporalmente/);
 console.log('OK: laboratorio V3 sin información inventada y recuperación ante errores.');
})().catch(e=>{console.error(e);process.exitCode=1;});
