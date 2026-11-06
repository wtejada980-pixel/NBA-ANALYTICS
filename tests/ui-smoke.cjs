'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const root = path.resolve(__dirname,'..');
const source = fs.readFileSync(path.join(root,'assets/app.js'),'utf8');
const html = fs.readFileSync(path.join(root,'index.html'),'utf8');
const getDate = () => {
  const parts = new Intl.DateTimeFormat('en-US',{timeZone:'America/Santo_Domingo',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const val = key => parts.find(p=>p.type===key).value;
  return val('year')+'-'+val('month')+'-'+val('day');
};

async function mount(snapshot, failure=false) {
  const nodes = new Map();
  function node(id) {
    if(!nodes.has(id)) nodes.set(id,{
      textContent: id==='seed' ? JSON.stringify({as_of:null, games:[]}) : '',
      innerHTML: '', className:'', disabled:false, listeners:{},
      addEventListener(event,callback){this.listeners[event]=callback;},
      querySelectorAll(){return [];}
    });
    return nodes.get(id);
  }
  const context = {
    document:{getElementById:node},Intl,Date,console,
    location:{protocol:'https:'},
    fetch: async () => failure? Promise.reject(new Error('network')) :
      {ok:true,json:async()=>snapshot}
  };
  vm.runInNewContext(source,context);
  await new Promise(r=>setTimeout(r,20));
  return {node};
}

(async () => {
  assert.match(html,/id="games"/);
  assert.doesNotMatch(html,/id="details"|id="validation"|id="export"/);
  const today=getDate(),future=new Date(Date.now()+3*3600_000).toISOString();
  const game={
    id:'test-123', date:today, datetime:future, status:'pre',
    away:{id:'1',abbr:'BOS',name:'Boston Celtics'},
    home:{id:'2',abbr:'NYK',name:'New York Knicks'},
    prediction:{away_pct:36.6,home_pct:63.4,reason:'Ventaja por localía y mejor forma reciente.'}
  };
  let view=await mount({as_of:new Date().toISOString(),date:today,games:[game]});
  assert.match(view.node('games').innerHTML,/Boston Celtics/);
  assert.match(view.node('games').innerHTML,/New York Knicks/);
  assert.match(view.node('games').innerHTML,/36\.6/);
  assert.match(view.node('games').innerHTML,/63\.4/);
  assert.match(view.node('games').innerHTML,/Ventaja por localía/);
  assert.doesNotMatch(view.node('games').innerHTML,/Brier|Elo|Noticias|Lesiones|últimos partidos/i);
  assert.equal(view.node('game-count').textContent,'1 partido');
  view=await mount({as_of:new Date(Date.now()-48*3600_000).toISOString(),games:[game]});
  assert.doesNotMatch(view.node('games').innerHTML,/63\.4/);
  assert.match(view.node('alert').textContent,/no mostramos porcentajes desfasados/i);
  view=await mount({as_of:new Date().toISOString(),games:[{...game,status:'post'}]});
  assert.doesNotMatch(view.node('games').innerHTML,/63\.4/);
  assert.match(view.node('games').innerHTML,/finalizó/);
  view=await mount({as_of:new Date().toISOString(),games:[{...game,prediction:{away_pct:60,home_pct:60}}]});
  assert.doesNotMatch(view.node('games').innerHTML,/>60\.0/);
  view=await mount({as_of:new Date().toISOString(),games:[{...game,prediction:{away_pct:50,home_pct:50,reason:'Encuentro equilibrado; sin favorito claro.'}}]});
  assert.doesNotMatch(view.node('games').innerHTML,/MÁS PROBABLE/);
  assert.match(view.node('games').innerHTML,/sin favorito claro/);
  view=await mount(null,true);
  assert.match(view.node('alert').textContent,/No se pudo actualizar/);
  console.log('OK: diseño mínimo, porcentajes, resumen, datos viejos, finalizados y fallos de red.');
})().catch(e=>{console.error(e);process.exitCode=1;});
