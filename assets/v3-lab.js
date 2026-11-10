'use strict';
(() => {
  const element = document.getElementById('v3-lab-content');
  if (!element) return;
  const escaped = value => String(value ?? '').replace(/[&<>"']/g, ch =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const pct = value => Number.isFinite(value) && value >= 0 && value <= 100 ?
    value.toFixed(1)+'%' : '—';
  const brier = value => Number.isFinite(value) && value >= 0 && value <= 1 ?
    value.toFixed(5) : '—';
  const fmt = instant => {
    const when = new Date(instant);
    if (!Number.isFinite(when.getTime())) return 'Hora sin confirmar';
    return new Intl.DateTimeFormat('es-DO',{timeZone:'America/Santo_Domingo',
      month:'short',day:'numeric',hour:'numeric',minute:'2-digit'}).format(when);
  };
  function card(name, metrics, emphasize=false) {
    return '<div class="v3-test-card'+(emphasize?' active':'')+'">'+
      '<strong>'+escaped(name)+'</strong>'+
      '<span class="v3-accuracy">'+pct(metrics?.winner_accuracy_pct)+'</span>'+
      '<span class="v3-score">Brier '+brier(metrics?.brier)+
      ' · '+(Number.isInteger(metrics?.n)?metrics.n:0)+' partidos</span></div>';
  }
  function render(evaluation,shadow,snapshot) {
    const holdout = evaluation?.segments?.test;
    const prospective = shadow?.prospective;
    const forecasts = shadow?.forecasts || {};
    const now = Date.now();
    const games = new Map((snapshot?.games||[]).map(g=>[String(g.id),g]));
    const upcoming = Object.entries(forecasts).filter(([id,row]) =>
      row && Number.isFinite(Date.parse(row.scheduled_at)) &&
      Date.parse(row.scheduled_at)>now &&
      Date.parse(row.predicted_at)<Date.parse(row.scheduled_at) &&
      Number.isFinite(row.v3_home_pct) &&
      Number.isFinite(row.v2_original_home_pct)).sort((a,b)=>
      Date.parse(a[1].scheduled_at)-Date.parse(b[1].scheduled_at)).slice(0,8);
    const n = Number.isInteger(holdout?.v3?.n) ? holdout.v3.n : 0;
    let content = '<div class="v3-shadows"><h3>Temporada 2025-26 · prueba fuera del entrenamiento</h3>';
    if (n) {
      content += '<p>Comparación sobre los mismos '+n+' partidos. Menor Brier = mejor calidad de probabilidades.</p>'+
        '<div class="v3-test-cards">'+
        card('V3 experimental',holdout.v3,true)+
        card('V2 reconstruido*',holdout.v2_reconstructed_without_players)+
        card('Elo de referencia',holdout.elo)+'</div>'+
        '<p class="v3-compare-warning">*El V2 histórico se reconstruyó sin estadísticas individuales de jugadores que no estaban guardadas. '+
        'La mejora de aciertos del V3 no implica por sí sola mejores probabilidades ni rentabilidad. '+
        'Por eso seguimos usando el V2 original en la página.</p>';
    } else {
      content += '<p class="v3-compare-warning">Aún no hay temporadas suficientes para comparar el V3 de manera independiente.</p>';
    }
    content += '</div><div class="v3-shadows"><h3>Prueba real V3 vs. V2 · pronósticos registrados</h3>'+
      '<p>Estos son los que se guardaron antes del inicio. No incluimos pronósticos reconstruidos después de conocer los marcadores.</p>'+
      '<div class="v3-prospective">'+
      card('V2 en los mismos partidos',prospective?.v2_original)+
      card('V3 registrado antes',prospective?.v3_shadow,true)+
      '<div class="v3-test-card"><strong>Partidos evaluados</strong><span class="v3-accuracy">'+
        (Number.isInteger(prospective?.n)?prospective.n:0)+
      '</span><span class="v3-score">Ambos modelos sobre el mismo resultado</span></div></div>';
    content += '<h3>Próximos pronósticos V3 en observación</h3>';
    if (upcoming.length) {
      content += upcoming.map(([id,row])=>{
        const game=games.get(String(id));
        const home=game?.home?.name||'Local';
        const away=game?.away?.name||'Visitante';
        const valid=(p)=>Number.isFinite(p)&&p>=0&&p<=100;
        const favor=(p)=>valid(p)?(p>=50?home:away)+' '+pct(Math.max(p,100-p)):'—';
        return '<div class="v3-row"><div class="v3-team-names">'+escaped(away)+' vs. '+
          escaped(home)+'<small>'+escaped(fmt(row.scheduled_at))+' · RD</small></div>'+
          '<div class="v3-pct"><span>V2 original</span><strong>'+
          escaped(favor(row.v2_original_home_pct))+'</strong></div>'+
          '<div class="v3-pct"><span>V3 en prueba</span><strong>'+
          escaped(favor(row.v3_home_pct))+'</strong></div></div>';
      }).join('');
    } else {
      content += '<p class="history-empty">Sin pronósticos V3 pendientes por ahora. Se guardarán antes de comenzar los próximos encuentros.</p>';
    }
    const recorded=Object.keys(forecasts).length;
    content+='</div><p class="v3-not-validated">'+recorded+
      ' pronósticos V3 guardados antes del inicio. La prueba retrospectiva de noviembre se analiza aparte y NO cuenta como éxito prospectivo. '+
      'Sin garantía de ganancias; no se calculan hándicaps.</p>';
    element.innerHTML=content;
  }
  const cache='?v='+Date.now();
  Promise.all([
    fetch('data/v3/evaluation.json'+cache,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('evaluation');return r.json();}),
    fetch('data/v3/shadow.json'+cache,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('shadow');return r.json();}),
    fetch('data/latest.json'+cache,{cache:'no-store'}).then(r=>{if(!r.ok)throw Error('latest');return r.json();})
  ]).then(([evaluation,shadow,snapshot])=>render(evaluation,shadow,snapshot))
    .catch(()=>{element.textContent='La comparación V3 no está disponible temporalmente. El V2 y los marcadores siguen funcionando.';});
})();