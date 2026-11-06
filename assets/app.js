'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const esc = input => String(input ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const seed = JSON.parse($('seed').textContent);
  let data = seed;
  let chosenDate = seed.date;
  const timeZone = 'America/Santo_Domingo';
  const percent = n => (typeof n === 'number' && Number.isFinite(n) ? `${n.toFixed(1)}%` : '—');
  const dayLabel = date => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date || '')) return date || 'Fecha desconocida';
    return new Intl.DateTimeFormat('es-DO', {day:'numeric', month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(date+'T12:00:00Z'));
  };
  const timeLabel = iso => {
    try { return new Intl.DateTimeFormat('es-DO', {hour:'numeric',minute:'2-digit',hour12:true,timeZone}).format(new Date(iso)); }
    catch {return '—';}
  };
  const recentStr = row => `${esc(row.win?'V':'D')} ${esc(row.points)}–${esc(row.opponent_points)} ${esc(row.opponent)}`;
  const good = p => p && Number.isFinite(p.home_pct) && Number.isFinite(p.away_pct);
  const srcLink = url => /^https:\/\//i.test(url || '') ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Ver ficha del partido ↗</a>` : '';
  function dateTabs(games) {
    const dates = [...new Set(games.map(g => g.date))].sort();
    if (!dates.includes(chosenDate)) chosenDate = dates[0] || '';
    $('date-tabs').innerHTML = dates.map(date => `<button type="button" data-date="${esc(date)}" class="${date === chosenDate?'selected':''}">${esc(dayLabel(date))}</button>`).join('');
    $('date-tabs').querySelectorAll('button').forEach(el => el.addEventListener('click', () => {
      chosenDate = el.dataset.date; render();
    }));
  }
  function teamCard(t, name) {
    if (!t) return `<section class="team-card"><h3>${esc(name)}</h3><p>Esperando estadísticas deportivas.</p></section>`;
    const f = t.form || {};
    const recent = (f.recent || []).map(r => `<div class="result"><span class="${r.win?'win':'loss'}">${recentStr(r)}</span><span>${esc(dayLabel(r.date))}</span></div>`).join('') || `<p class="tiny">No hay resultados suficientes.</p>`;
    const players = (t.players || []).length ? `<div class="player-scroll"><table class="player-table"><thead><tr><th>JUGADOR</th><th>PTS</th><th>REB</th><th>AST</th></tr></thead><tbody>${t.players.map(p => `<tr><td>${esc(p.name)} <span class="tiny">(${p.games} j.)</span></td><td>${Number(p.pts).toFixed(1)}</td><td>${Number(p.reb).toFixed(1)}</td><td>${Number(p.ast).toFixed(1)}</td></tr>`).join('')}</tbody></table></div>` : `<p class="tiny">Sin box scores suficientes; el cálculo del equipo puede continuar sin este ajuste.</p>`;
    return `<section class="team-card"><h3>${esc(t.name || name)}</h3><p>${f.played || 0} partidos analizados · ${f.wins || 0} victorias · margen ponderado ${(f.margin ?? 0) > 0 ? '+' : ''}${esc(f.margin ?? 0)} · anota ${esc(f.points_for ?? '—')} · recibe ${esc(f.points_against ?? '—')} pts/juego · descanso ${t.rest_days ?? '—'} día(s)</p><h4>ÚLTIMOS PARTIDOS</h4><div class="results">${recent}</div><h4>JUGADORES DESTACADOS (PROMEDIO RECIENTE)</h4>${players}</section>`;
  }
  function contextPanel(g) {
    const c = g.context;
    if (!c) return '<p class="tiny">No hay revisión adicional de lesiones, noticias y foros para este partido. Consultar las fuentes oficiales antes de interpretarlo.</p>';
    const injuries = ['away','home'].map(side=>{
      const d=c.injuries?.[side] || {};
      const items=d.items || [];
      const rows=items.length ? items.map(i=>'<li>'+esc(i.player)+' — '+esc(i.status)+(i.reason?' ('+esc(i.reason)+')':'')+'</li>').join('') : '<li>No hay ausencias verificadas en esta fuente; NO significa plantilla completa.</li>';
      return '<div class="context-box"><h4>'+esc(g[side].name)+'</h4><p class="tiny">Fuente: '+esc(d.source || 'No verificada')+'</p><ul>'+rows+'</ul></div>';
    }).join('');
    const news=(c.news || []).map(n=>'<li><a href="'+esc(n.url)+'" target="_blank" rel="noopener noreferrer">'+esc(n.title)+'</a></li>').join('') || '<li>Sin noticias verificadas por este proceso.</li>';
    const f=c.forum || {};
    const posts=(f.posts||[]).map(p=>'<li><a href="'+esc(p.url)+'" target="_blank" rel="noopener noreferrer">'+esc(p.title)+'</a></li>').join('') || '<li>No se recuperaron publicaciones autenticadas.</li>';
    const discussion = /^https:\/\/www\.reddit\.com\/r\/nba\/search\//.test(f.discussion_url||'') ? '<a href="'+esc(f.discussion_url)+'" target="_blank" rel="noopener noreferrer">Abrir búsqueda en r/nba ↗</a>' : '';
    const official = /^https:\/\//.test(c.official_injury_report||'') ? '<a href="'+esc(c.official_injury_report)+'" target="_blank" rel="noopener noreferrer">Informe oficial NBA ↗</a>' : '';
    return '<div class="context-section"><h3>Noticias, lesiones y conversación pública</h3><p class="tiny">El análisis de aficionados aporta contexto, no certeza estadística. Los porcentajes anteriores no se ajustan automáticamente por rumores ni bajas sin verificar.</p><div class="cols">'+injuries+'</div><p class="tiny">'+official+'</p><h4>Noticias recientes</h4><ul>'+news+'</ul><h4>Comunidad y foros · '+esc(f.status||'No conectado')+'</h4><ul>'+posts+'</ul><p class="tiny">'+discussion+'</p></div>';
  }
  function render() {
    const games = Array.isArray(data.games) ? data.games : [];
    dateTabs(games);
    const shown = games.filter(g => g.date === chosenDate);
    $('count-games').textContent = games.length;
    $('count-preds').textContent = games.filter(g => good(g.prediction)).length;
    $('count-validated').textContent = data.validation?.completed_predictions ?? 0;
    $('updated').textContent = data.as_of ? new Intl.DateTimeFormat('es-DO',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone}).format(new Date(data.as_of))+' RD' : 'Datos iniciales sin actualizar';
    $('source').textContent = data.source || 'ESPN (consulta de servidor)';
    $('rows').innerHTML = shown.map(g => {
      const p = g.prediction;
      const available = good(p);
      const a = available ? p.away_pct : null, h = available ? p.home_pct : null;
      const fav = !available ? 'Sin datos suficientes' : a > h ? g.away.name : g.home.name;
      return `<tr><td><div class="teams"><span class="abbr">${esc(g.away.abbr)}</span><span class="vs">@</span><span class="abbr">${esc(g.home.abbr)}</span></div><div class="sub">${esc(g.away.name)} vs. ${esc(g.home.name)}</div></td><td><div class="pct ${available && a>h?'top':''}">${percent(a)}</div>${available?`<div class="bar"><span style="width:${Math.max(0,Math.min(100,a))}%"></span></div>`:''}<span class="sub">${esc(g.away.abbr)}</span></td><td><div class="pct ${available && h>a?'top':''}">${percent(h)}</div>${available?`<div class="bar"><span style="width:${Math.max(0,Math.min(100,h))}%"></span></div>`:''}<span class="sub">${esc(g.home.abbr)}</span></td><td><span class="fav">${esc(fav)}</span>${available?`<span class="softtag">Modelo experimental</span>`:''}</td><td>${timeLabel(g.datetime)}<div class="sub">${esc(g.status === 'post' ? 'Finalizado' : g.status === 'in' ? 'En juego' : 'Programado')}</div></td></tr>`;
    }).join('') || `<tr><td colspan="5" class="empty">No hay partidos de NBA en esta fecha según los datos publicados.</td></tr>`;
    $('details').innerHTML = shown.map(g => {
      const p = g.prediction;
      const factors = p?.factors || {};
      const factorText = good(p) ? `Modelo ${p.model || 'experimental'} · localía ${factors.home_advantage_points ?? '?'} pts · Elo ${factors.elo_component ?? '?'} pts · forma ${factors.recent_margin_component ?? '?'} pts · victorias ${factors.recent_wins_component ?? '?'} pts · ataque/defensa ${factors.scoring_component ?? '?'} pts · descanso ${factors.rest_component ?? '?'} pts · jugadores ${factors.player_component ?? '?'} pts · muestra ${p.sample_games_per_team_min ?? '?'} partidos · confianza ${p.confidence ?? 'limitada'}` : 'El sistema no puede calcular porcentajes aún: se necesitan al menos cuatro partidos previos de cada equipo.';
      return `<details><summary>${esc(g.away.name)} vs. ${esc(g.home.name)} <span class="tiny">Ver explicación, jugadores y noticias</span></summary><div class="detail-inner"><p class="tiny">${esc(factorText)}</p><div class="cols">${teamCard(data.teams?.[g.away.id],g.away.name)}${teamCard(data.teams?.[g.home.id],g.home.name)}</div><p class="tiny">${srcLink(g.source)}</p>${contextPanel(g)}</div></details>`;
    }).join('') || '<p class="tiny">Sin partidos para analizar.</p>';
    const v = data.validation || {};
    const n = Number(v.completed_predictions) || 0;
    if (n && Number.isFinite(v.brier_score)) {
      const rows = (v.calibration || []).map(b => `<tr><td>${esc(b.range)}</td><td>${esc(b.count)}</td><td>${esc(b.average_predicted_pct)}%</td><td>${esc(b.actual_home_win_pct)}%</td></tr>`).join('');
      const byModel = Object.entries(v.by_model || {}).map(([model,m]) => `<li>${esc(model)}: ${esc(m.n)} partidos, Brier ${esc(m.brier)}</li>`).join('');
      $('validation').innerHTML = `<div class="validation-stats"><div><strong>${esc(n)}</strong><span>Predicciones resueltas</span></div><div><strong>${esc(v.favorite_accuracy_pct ?? '—')}%</strong><span>Aciertos del favorito</span></div><div><strong>${esc(v.brier_score)}</strong><span>Brier (menos es mejor)</span></div></div><p>Referencia simple al 50%: Brier 0.25. ${esc(v.sample_warning || '')} No prueba rentabilidad.</p>${rows ? `<div class="table-wrap"><table class="calibration-table"><thead><tr><th>PROBABILIDAD</th><th>PARTIDOS</th><th>PROMEDIO PRONOSTICADO</th><th>VICTORIAS REALES LOCAL</th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}${byModel ? `<p>Por versión del modelo:</p><ul>${byModel}</ul>` : ''}`;
    } else {
      $('validation').textContent = 'Todavía no hay pronósticos resueltos con datos verificados. Registramos la primera predicción antes de empezar cada partido y comprobamos luego el resultado.';
    }
  }
  function setNotice(message, type='') {
    $('alert').textContent = message;
    $('alert').className = `notice ${type}`;
    $('status-dot').className = `indicator ${type === 'ok' ? 'ok' : type === 'error' ? 'err' : ''}`;
    $('status-label').textContent = type === 'ok' ? 'Datos guardados' : type === 'error' ? 'Datos no disponibles' : 'Esperando actualización';
  }
  async function update() {
    if (location.protocol === 'file:') {
      data = seed;
      setNotice('Modo local: esta vista se abre sin servidor. Para ver datos actualizados automáticamente, publica el proyecto en GitHub Pages. Los encuentros de referencia no incluyen porcentajes.', 'error');
      render(); return;
    }
    try {
      const response = await fetch('data/latest.json?ts=' + Date.now(), {cache:'no-store'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const incoming = await response.json();
      if (!Array.isArray(incoming.games) || !incoming.teams || typeof incoming.teams !== 'object') throw new Error('Datos incompletos');
      data = incoming;
      const stale = !data.as_of || Date.now() - Date.parse(data.as_of) > 30*60*60*1000;
      setNotice(stale ? 'Mostrando el último informe disponible, pero lleva más de 30 horas sin actualizarse. Revisa GitHub Actions.' : 'Informe cargado. Las estimaciones son experimentales y provienen de estadísticas deportivas, no de cuotas.', stale ? 'error' : 'ok');
    } catch (error) {
      data = seed;
      setNotice('No pude cargar el informe publicado. La tabla de referencia se conserva sin probabilidades: ' + error.message, 'error');
    }
    render();
  }
  function exportCsv() {
    const games = (data.games || []).filter(g => g.date === chosenDate);
    const rows = [['fecha','visitante','probabilidad_visitante_pct','local','probabilidad_local_pct','fuente','actualizado'], ...games.map(g => [g.date,g.away.name,g.prediction?.away_pct ?? '',g.home.name,g.prediction?.home_pct ?? '',g.source,data.as_of ?? ''])];
    const csv = '\ufeff'+rows.map(row => row.map(v => '"'+String(v).replaceAll('"','""')+'"').join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([csv],{type:'text/csv;charset=utf-8'}));
    const a = document.createElement('a'); a.href=url; a.download=`NBA_Analytics_${chosenDate||'sin-fecha'}.csv`;a.click();
    setTimeout(() => URL.revokeObjectURL(url),1000);
  }
  $('reload').addEventListener('click',update);
  $('export').addEventListener('click',exportCsv);
  update();
})();
