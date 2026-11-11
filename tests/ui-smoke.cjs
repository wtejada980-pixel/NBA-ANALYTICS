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

async function mount(snapshot, failure=false, scoreboard=null) {
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
    fetch: async (url) => {
      if (failure) throw new Error('network');
      if (String(url).includes('site.api.espn.com')) {
        if (!scoreboard) throw new Error('ESPN no disponible en la prueba');
        return {ok:true,json:async()=>scoreboard};
      }
      return {ok:true,json:async()=>snapshot};
    }
  };
  vm.runInNewContext(source,context);
  await new Promise(r=>setTimeout(r,20));
  return {node};
}

(async () => {
  assert.match(html,/id="games"/);
  assert.match(html,/Historial: últimos 7 días/);
  assert.match(html,/id="scouting-games"/);
  assert.doesNotMatch(html,/thescore|theScore/i);
  assert.match(source,/const LIVE_INTERVAL_MS = 2000;/);
  assert.match(source,/const IDLE_INTERVAL_MS = 30000;/);
  assert.match(source,/visibilityState === 'hidden'/);
  assert.match(source,/nextLiveRetryAt/);
  assert.match(html,/id="model-validation"/);
  assert.match(html,/id="elo-validation"/);
  assert.match(html,/id="calibration-chart"/);
  assert.match(html,/id="model-versions"/);
  assert.match(html,/id="history-filter"/);
  assert.match(html,/data-history-filter="hit"/);
  assert.match(html,/data-history-filter="miss"/);
  assert.match(html,/data-history-filter="pending"/);
  assert.match(html,/skeleton-game/);
  assert.match(html,/skeleton-metric/);
  assert.match(source,/const sorted = safe\.slice\(\)\.sort/);
  assert.match(html,/id="data-health"/);
  assert.match(html,/id="history-list"/);
  assert.match(html,/id="quality-caveat"/);
  assert.doesNotMatch(html,/id="details"|id="export"/);
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
  const pastDate = new Date(Date.now()-86400000).toISOString().slice(0,10);
  const archiveGame={...game,id:'past',date:pastDate,status:'post',historical:true,
    home_score:112,away_score:108};
  const archiveView=await mount({as_of:new Date().toISOString(),
    date:today,games:[archiveGame,game]});
  assert.match(archiveView.node('date-tabs').innerHTML,/data-date=/);
  // Elegir fecha pasada en la interfaz y mostrar resultado verdadero.
  const historicalTab = archiveView.node('date-tabs').innerHTML;
  assert.match(historicalTab,new RegExp(pastDate));
  assert.match(source,/archive-note/);
  const revisionGame = {...game,
    prediction:{...game.prediction,predicted_at:new Date(Date.now()-3600_000).toISOString()},
    revised_prediction:{home_pct:57.2,away_pct:42.8,
      predicted_at:new Date().toISOString(),model:'elo-forma10-v2',reason:'Actualizado'}};
  const revisionView = await mount({as_of:new Date().toISOString(),date:today,games:[revisionGame]});
  assert.match(revisionView.node('games').innerHTML,/ACTUALIZADO PREPARTIDO/);
  assert.match(revisionView.node('games').innerHTML,/Primera predicción:/);
  assert.match(revisionView.node('games').innerHTML,/57\.2/);
  assert.match(revisionView.node('games').innerHTML,/63\.4/);
  assert.match(view.node('scouting-games').innerHTML,/Análisis descriptivo todavía no disponible/);
  const scoutGame = {...game, scouting:{
    favorite:'New York Knicks',favorite_pct_original:63.4,
    classification:'Ventaja moderada',
    away_form:{games:10,wins:6,margin:3.1},
    home_form:{games:10,wins:8,margin:6.2},
    observations:['Los equipos tienen una diferencia de rendimiento.']
  }};
  const scoutView = await mount({as_of:new Date().toISOString(),date:today,games:[scoutGame]});
  assert.match(scoutView.node('scouting-games').innerHTML,/New York Knicks · 63\.4%/);
  assert.match(scoutView.node('scouting-games').innerHTML,/diagnóstico|Diagnóstico/);
  assert.match(scoutView.node('scouting-games').innerHTML,/6 victorias en 10 juegos/);
  assert.doesNotMatch(view.node('games').innerHTML,/\bBrier\b|\bElo\b|Noticias|Lesiones|últimos partidos/i);
  assert.equal(view.node('game-count').textContent,'1 partido');
  assert.match(view.node('model-validation').innerHTML,/Partidos evaluados/);
  assert.match(view.node('quality-caveat').textContent,/Todavía no hay partidos/);
  assert.match(view.node('history-list').innerHTML,/Todavía no tenemos pronósticos/);
  view=await mount({as_of:new Date().toISOString(),date:today,games:[game],
    validation:{completed_predictions:8,favorite_accuracy_pct:62.5,brier_score:0.22,log_loss:0.68}});
  assert.match(view.node('model-validation').innerHTML,/62\.5%/);
  assert.match(view.node('model-validation').innerHTML,/accuracy-bar/);
  assert.match(view.node('model-validation').innerHTML,/0\.2200/);
  assert.match(view.node('quality-caveat').textContent,/Muestra inicial/);
  assert.match(view.node('calibration-chart').innerHTML,/resultados suficientes/);
  view=await mount({as_of:new Date().toISOString(),date:today,games:[game],
    validation:{completed_predictions:8,favorite_accuracy_pct:62.5,brier_score:0.22,log_loss:0.68,
      elo_comparison:{n:4,model_brier:.22,elo_brier:.25}},
    history_recent:[
      {id:'done',date:today,home:'New York Knicks',away:'Boston Celtics',
        home_pct:63.4,away_pct:36.6,model:'elo-forma10-v2',
        predicted_at:new Date(Date.now()-3*3600_000).toISOString(),
        scheduled_at:new Date(Date.now()+3*3600_000).toISOString(),
        result:{winner:'home',home_score:112,away_score:108}},
      {id:'late',date:today,home:'New York Knicks',away:'Boston Celtics',
        home_pct:60,away_pct:40,model:'v2',
        predicted_at:new Date(Date.now()+4*3600_000).toISOString(),
        scheduled_at:new Date(Date.now()+3*3600_000).toISOString(),result:null}
    ]});
  assert.match(view.node('elo-validation').innerHTML,/0\.2200/);
  assert.match(view.node('history-list').innerHTML,/ACIERTO/);
  assert.match(view.node('history-count').textContent,/1 de 1/);
  assert.match(view.node('data-health').textContent,/ESPN/);
  assert.doesNotMatch(view.node('history-list').innerHTML,/late/);
  assert.match(view.node('games').innerHTML,/Ver jugadores y titulares/);
  assert.match(view.node('games').innerHTML,/Forma de los equipos/);
  assert.match(view.node('games').innerHTML,/Tipo de pronóstico: ganador del partido/);
  assert.doesNotMatch(view.node('games').innerHTML,/theScore/i);
  assert.match(view.node('games').innerHTML,/<details class="game-card"/);
  view=await mount({as_of:new Date(Date.now()-48*3600_000).toISOString(),games:[game]});
  assert.doesNotMatch(view.node('games').innerHTML,/63\.4/);
  assert.match(view.node('games').innerHTML,/datos desactualizados/i);
  view=await mount({as_of:new Date().toISOString(),games:[{...game,status:'post'}]});
  assert.match(view.node('games').innerHTML,/63\.4/);
  assert.match(view.node('games').innerHTML,/ANTES del partido/);
  view=await mount({as_of:new Date().toISOString(),games:[{...game,prediction:{away_pct:60,home_pct:60}}]});
  assert.doesNotMatch(view.node('games').innerHTML,/>60\.0/);
  view=await mount({as_of:new Date().toISOString(),games:[{...game,prediction:{away_pct:50,home_pct:50,reason:'Encuentro equilibrado; sin favorito claro.'}}]});
  assert.doesNotMatch(view.node('games').innerHTML,/MÁS PROBABLE/);
  assert.match(view.node('games').innerHTML,/sin favorito claro/);

  // Scoreboard en vivo: se agregan juegos no incluidos en el snapshot,
  // se actualizan los tanteos y se conservan pronósticos prepartido.
  const event = (id, state, awayScore, homeScore) => ({
    id, date:future, status:{type:{state,shortDetail: 'Q2 06:30'}},
    competitions:[{competitors:[
      {homeAway:'home',team:{id:'2',abbreviation:'NYK',displayName:'New York Knicks'},score:homeScore},
      {homeAway:'away',team:{id:'1',abbreviation:'BOS',displayName:'Boston Celtics'},score:awayScore}
    ]}]
  });
  view=await mount({as_of:new Date().toISOString(),games:[game]},false,{
    events:[event('test-123','in','52','61'),event('test-456','pre','','')]
  });
  assert.match(view.node('games').innerHTML,/EN VIVO/);
  assert.match(view.node('games').innerHTML,/live-score">52/);
  assert.match(view.node('games').innerHTML,/live-score">61/);
  assert.match(view.node('games').innerHTML,/63\.4/);
  assert.equal(view.node('game-count').textContent,'2 partidos');
  view=await mount({
    as_of:new Date().toISOString(),games:[game],
    teams:{
      '1':{players:[{id:'10',name:'Jugador de Boston',games:5,pts:21.4}]},
      '2':{players:[{id:'11',name:'Jugador de NY',games:4,pts:18.7}]}
    }
  });
  assert.match(view.node('games').innerHTML,/Jugador de Boston/);
  assert.match(view.node('games').innerHTML,/21\.4/);
  assert.match(view.node('games').innerHTML,/18\.7/);
  assert.match(view.node('games').innerHTML,/Titulares sin confirmar/);
  view=await mount(null,true);
  assert.match(view.node('alert').textContent,/No fue posible conectar/);
  console.log('OK: probabilidades prepartido, marcador vivo, agenda y errores de red.');
})().catch(e=>{console.error(e);process.exitCode=1;});
