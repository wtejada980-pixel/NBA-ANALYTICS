'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const zone = 'America/Santo_Domingo';
  const seed = JSON.parse($('seed').textContent);
  let data = seed;
  let chosenDate = '';
  let activeHistoryFilter = 'all';
  let loadError = false;
  let liveAvailable = false;
  let liveError = false;
  let liveUpdatedAt = 0;
  // Consultar marcadores cada 2 segundos SOLO cuando hay un partido en juego
  // y la pestaña está visible. ESPN puede actualizar con retraso o limitar acceso.
  const LIVE_INTERVAL_MS = 2000;
  const IDLE_INTERVAL_MS = 30000;
  const PLAYER_INTERVAL_MS = 12000;
  let livePollInFlight = false;
  let lastLivePollStarted = 0;
  let lastPlayersPollStarted = 0;
  let nextLiveRetryAt = 0;
  let liveFailures = 0;
  let expandedGameId = '';
  const livePlayerDetails = new Map();

  function todayInRD() {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(new Date());
    const get = type => parts.find(part => part.type === type).value;
    return get('year') + '-' + get('month') + '-' + get('day');
  }
  chosenDate = todayInRD();

  function dateLabel(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return 'Fecha desconocida';
    const date = new Date(value + 'T12:00:00Z');
    return new Intl.DateTimeFormat('es-DO', {
      timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short'
    }).format(date);
  }
  function timeLabel(iso) {
    const d = new Date(iso);
    return Number.isFinite(d.getTime()) ?
      new Intl.DateTimeFormat('es-DO', {timeZone: zone, hour:'numeric', minute:'2-digit', hour12:true}).format(d) :
      'Hora por confirmar';
  }
  function isFresh() {
    const when = Date.parse(data.as_of || '');
    const age = Date.now() - when;
    return !loadError && Number.isFinite(when) && age >= -15*60*1000 && age < 30*60*60*1000;
  }
  function validPrediction(game) {
    const p = game.prediction;
    if (!isFresh() || !p || !Number.isFinite(p.home_pct) || !Number.isFinite(p.away_pct)) return false;
    return p.home_pct >= 0 && p.away_pct >= 0 &&
      p.home_pct <= 100 && p.away_pct <= 100 &&
      Math.abs(p.home_pct + p.away_pct - 100) <= 0.2;
  }
  function formatPct(n) {
    return Number(n).toFixed(1);
  }
  function probabilityTone(n) {
    return n >= 65 ? 'prob-fuerte' : n >= 55 ? 'prob-media' : 'prob-baja';
  }
  function stateLabel(game) {
    if (game.status === 'post') return 'FINALIZADO';
    if (game.status === 'in') return 'EN VIVO' + (game.status_detail ? ' · ' + game.status_detail : '');
    if (Date.parse(game.datetime) <= Date.now()) return 'POR CONFIRMAR';
    return 'PROGRAMADO';
  }
  function shortReason(game, allowed) {
    if (!allowed) {
      if (!isFresh()) return 'No se muestra ninguna estimación con datos desactualizados.';
      return 'No hay suficientes datos para estimar este enfrentamiento.';
    }
    const reason = typeof game.prediction?.reason === 'string' ? game.prediction.reason.trim() : '';
    if (game.status === 'in' || game.status === 'post') {
      return 'Pronóstico ANTES del partido. No representa la probabilidad de ganar durante el juego.';
    }
    return reason ? reason.slice(0, 150) :
      'Estimación basada en rendimiento, forma reciente y localía.';
  }
  function logoFor(team) {
    const values = {
      GSW:'gs', NYK:'ny', SAS:'sa', NOP:'no', UTA:'utah', UTAH:'utah',
      PHX:'phx', WSH:'wsh', BKN:'bkn', CHA:'cha', OKC:'okc', DEN:'den',
      IND:'ind', BOS:'bos', ATL:'atl', TOR:'tor', MEM:'mem'
    };
    const abbr = String(team?.abbr || '').toUpperCase().replace(/[^A-Z]/g,'');
    const slug = values[abbr] || abbr.toLowerCase();
    return 'https://a.espncdn.com/i/teamlogos/nba/500/' + encodeURIComponent(slug) + '.png';
  }

  function normalizedName(name) {
    return String(name || '').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toLowerCase();
  }

  function parseGameSummary(summary, game) {
    const result = {away:[],home:[]};
    const teams = summary?.boxscore?.players;
    if (!Array.isArray(teams)) return result;
    for (const group of teams) {
      const tid = String(group?.team?.id || '');
      const side = tid === String(game.away?.id) ? 'away' :
        tid === String(game.home?.id) ? 'home' : '';
      if (!side) continue;
      for (const block of group.statistics || []) {
        const labels = (block.labels || []).map(x => String(x).toUpperCase());
        if (!labels.includes('PTS')) continue;
        const ptsIndex = labels.indexOf('PTS');
        for (const row of block.athletes || []) {
          if (row.didNotPlay || !row.athlete?.id) continue;
          const raw = Array.isArray(row.stats) ? row.stats[ptsIndex] : null;
          const pts = raw !== null && raw !== '' && raw !== undefined && Number.isFinite(Number(raw)) ?
            Number(raw) : null;
          result[side].push({
            id:String(row.athlete.id),
            name:String(row.athlete.displayName || row.athlete.fullName || 'Jugador'),
            starter:row.starter === true || row.isStarter === true,
            game_pts:game.status === 'pre' ? null : pts
          });
        }
      }
    }
    return result;
  }

  function playersForSide(game, side) {
    const tid = String(game[side]?.id || '');
    const recent = Array.isArray(data.teams?.[tid]?.players) ? data.teams[tid].players : [];
    const confirmed = livePlayerDetails.get(String(game.id)) || game.lineups || {};
    const boxscore = Array.isArray(confirmed[side]) ? confirmed[side] : [];
    const map = new Map();
    const key = p => p.id ? 'id:' + String(p.id) : 'name:' + normalizedName(p.name);
    for (const p of recent) {
      if (p?.name) map.set(key(p), {
        id:String(p.id || ''),name:String(p.name),games:Number(p.games) || 0,
        pts:Number.isFinite(Number(p.pts)) ? Number(p.pts) : null,
        starter:false,game_pts:null
      });
    }
    for (const p of boxscore) {
      if (!p?.name) continue;
      const idKey = key(p);
      let existing = map.get(idKey);
      if (!existing) existing = [...map.values()].find(x => normalizedName(x.name) === normalizedName(p.name));
      const record = existing ? {...existing} : {
        id:String(p.id || ''),name:String(p.name),games:0,pts:null,starter:false,game_pts:null
      };
      record.starter = p.starter === true;
      if (game.status !== 'pre' && p.game_pts !== null && Number.isFinite(Number(p.game_pts))) {
        record.game_pts = Number(p.game_pts);
      }
      map.set(idKey,record);
    }
    return [...map.values()].sort((a,b)=>Number(b.starter)-Number(a.starter) ||
      (b.pts ?? -1)-(a.pts ?? -1)).slice(0,15);
  }

  function playerTable(game, side) {
    const team = game[side] || {};
    const players = playersForSide(game,side);
    const starters = players.filter(p=>p.starter);
    const avg = p => p.pts === null || p.games < 1 ? '—' : formatPct(p.pts);
    const todayPts = p => p.game_pts === null ? '—' : String(p.game_pts);
    const rows = players.map(p => '<tr>' +
      '<td class="player-name">' + escapeHtml(p.name) +
      (p.starter ? '<span class="starter-badge">TITULAR</span>' : '') +
      '</td><td class="player-avg">' + avg(p) + '</td>' +
      '<td class="player-today">' + todayPts(p) + '</td></tr>').join('');
    const hint = starters.length === 5 ? '5 titulares confirmados en el acta de ESPN' :
      starters.length > 0 ? starters.length + ' titulares identificados por ESPN; quinteto incompleto' :
      'Titulares sin confirmar · jugadores ordenados por promedio reciente';
    return '<div class="player-team">' +
      '<h4>' + escapeHtml(team.name || 'Equipo') + '</h4>' +
      '<p class="lineup-note">' + escapeHtml(hint) + '</p>' +
      (players.length ? '<table class="players-table"><thead><tr>' +
        '<th>Jugador</th><th>Prom. PTS</th><th>Hoy</th></tr></thead><tbody>' +
        rows + '</tbody></table>' :
        '<div class="players-empty">No hay estadísticas individuales verificadas para este equipo.</div>') +
    '</div>';
  }
  function playersPanel(game) {
    return '<div class="players-panel-title">Jugadores y quintetos iniciales</div>' +
      '<p class="players-explainer">Prom. PTS = promedio de puntos en hasta los últimos 5 partidos registrados de cada jugador. ' +
      '«Hoy» = puntos anotados en este encuentro cuando ESPN los publica. ' +
      'No es una predicción de puntos.</p>' +
      '<div class="player-columns">' + playerTable(game,'away') + playerTable(game,'home') + '</div>';
  }
  function safeArticleUrl(value) {
    try {
      const url = new URL(String(value || ''));
      const host = url.hostname.toLowerCase();
      const allowed = ['foxsports.com','news.google.com','espn.com','nba.com'];
      return url.protocol === 'https:' && allowed.some(domain => host === domain || host.endsWith('.' + domain)) ? url.href : '';
    } catch (error) { return ''; }
  }
  function newsLink(item, className = 'news-link') {
    const href = safeArticleUrl(item?.url);
    if (!href || !item?.title) return '';
    const source = String(item.source || 'Fuente deportiva');
    const published = String(item.published || '');
    return '<a class="' + className + '" href="' + escapeHtml(href) + '" target="_blank" rel="noopener noreferrer">' +
      '<span class="news-card-source">' + escapeHtml(source) + (published ? ' · ' + escapeHtml(published) : '') + '</span>' +
      '<strong>' + escapeHtml(item.title) + '</strong><span class="news-open">Leer en la fuente ↗</span></a>';
  }
  function renderNews() {
    const items = Array.isArray(data.news) ? data.news.slice(0, 10) : [];
    const cards = items.map(item => newsLink(item, 'news-card noticia-card')).filter(Boolean);
    $('news-list').innerHTML = cards.length ? cards.join('') :
      '<p class="history-empty">No hay titulares recientes disponibles. Revisa <a href="https://www.foxsports.com/stories/nba" target="_blank" rel="noopener noreferrer">FOX Sports NBA ↗</a>.</p>';
    const raw = Date.parse(data.news_updated_at || '');
    const source = String(data.news_source || 'Fuentes NBA');
    $('news-updated').textContent = Number.isFinite(raw) ?
      source + ' · actualizado ' + timeLabel(new Date(raw).toISOString()) + ' RD' : source + ' · fecha no disponible';
  }
  function contextPanel(game) {
    const context = game.context && typeof game.context === 'object' ? game.context : {};
    if (!game.context || typeof game.context !== 'object') return '';
    const injuries = context.injuries && typeof context.injuries === 'object' ? context.injuries : {};
    const sideStatus = side => {
      const team = game[side] || {};
      const report = injuries[side] || {};
      const rows = Array.isArray(report.items) ? report.items : [];
      const detail = rows.length ? rows.slice(0, 6).map(row =>
        '<li><strong>' + escapeHtml(row.player || 'Jugador') + '</strong><span>' +
        escapeHtml(row.status || 'Estado reportado') + (row.reason ? ' · ' + escapeHtml(row.reason) : '') + '</span></li>'
      ).join('') : '<li class="injury-empty">ESPN no publicó estados en esta consulta; no significa que todos estén disponibles.</li>';
      const source = safeArticleUrl(report.source);
      return '<div class="context-team"><h4>' + escapeHtml(team.name || 'Equipo') + '</h4><ul>' + detail + '</ul>' +
        (source ? '<a href="' + escapeHtml(source) + '" target="_blank" rel="noopener noreferrer">Fuente: ESPN ↗</a>' : '') + '</div>';
    };
    const news = Array.isArray(context.news) ? context.news.map(item => newsLink(item, 'context-news-link')).filter(Boolean) : [];
    const official = safeArticleUrl(context.official_injury_report);
    const updated = Date.parse(context.context_updated_at || '');
    return '<section class="context-panel" aria-label="Disponibilidad y noticias relacionadas">' +
      '<div class="context-heading"><h3>Disponibilidad y noticias</h3>' +
      (Number.isFinite(updated) ? '<span>Consulta · ' + escapeHtml(timeLabel(new Date(updated).toISOString())) + ' RD</span>' : '') + '</div>' +
      '<div class="context-teams">' + sideStatus('away') + sideStatus('home') + '</div>' +
      (official ? '<a class="official-injury-link" href="' + escapeHtml(official) + '" target="_blank" rel="noopener noreferrer">Ver el informe oficial de lesiones de la NBA ↗</a>' : '') +
      '<h4 class="context-news-heading">Noticias relacionadas</h4>' +
      (news.length ? '<div class="context-news-list">' + news.slice(0, 4).join('') + '</div>' :
        '<p class="context-news-empty">No hay titulares relacionados disponibles para este partido.</p>') +
      '<p class="context-note">Lesiones y noticias son contexto informativo; no alteran el pronóstico prepartido.</p></section>';
  }
  async function fetchGameSummary(id) {
    if (!/^\d+$/.test(id)) return;
    const game = (data.games || []).find(g=>String(g.id)===id);
    if (!game) return;
    try {
      const url='https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=' +
        encodeURIComponent(id);
      const response=await fetch(url,{cache:'no-store'});
      if (!response.ok) return;
      const result=parseGameSummary(await response.json(),game);
      if (!result.away.length && !result.home.length) return;
      livePlayerDetails.set(id,result);
      if (expandedGameId === id) render();
    } catch (error) {
      // Si ESPN impide la consulta en el navegador, conservar promedios
      // recopilados por GitHub Actions y la última alineación conocida.
    }
  }


  function teamPerformance(game, side) {
    const team = game[side] || {};
    const form = data.teams?.[String(team.id)]?.form || {};
    const matches = Number.isInteger(form.played) ? form.played : 0;
    const wins = Number.isInteger(form.wins) ? form.wins : null;
    const fmt = n => Number.isFinite(n) ? n.toFixed(1) : '—';
    const results = Array.isArray(form.recent) ? form.recent.slice(0, 5) : [];
    const recent = results.map(g => '<span class="form-game ' + (g.win ? 'form-win' : 'form-loss') +
      '" title="' + escapeHtml(g.date || '') + ': ' + escapeHtml(g.opponent || '') +
      ' ' + (Number.isFinite(g.points) ? g.points : '—') + '-' +
      (Number.isFinite(g.opponent_points) ? g.opponent_points : '—') + '">' +
      (g.win ? 'V' : 'D') + '</span>').join('');
    return '<div class="form-team"><h4>' + escapeHtml(team.name || 'Equipo') +
      '</h4><div class="form-stats">' +
      '<div><span>Récord reciente</span><strong>' + (wins === null || !matches ? '—' : wins + '-' + (matches-wins)) + '</strong></div>' +
      '<div><span>PTS a favor</span><strong>' + fmt(form.points_for) + '</strong></div>' +
      '<div><span>PTS recibidos</span><strong>' + fmt(form.points_against) + '</strong></div>' +
      '</div><div class="form-last">' + (recent || '<span class="muted-copy">Sin partidos recientes</span>') +
      '</div></div>';
  }
  function matchupInsights(game) {
    const matchups = Array.isArray(game.head_to_head) ? game.head_to_head.slice(0, 5) : [];
    const list = matchups.map(g => '<li><span>' + escapeHtml(g.date || '') + '</span>' +
      '<strong>' + escapeHtml(g.away || '') + ' ' + (Number.isFinite(g.away_score) ? g.away_score : '—') +
      ' – ' + (Number.isFinite(g.home_score) ? g.home_score : '—') + ' ' +
      escapeHtml(g.home || '') + '</strong></li>').join('');
    return '<div class="insights-title">Forma de los equipos</div>' +
      '<p class="insights-note">Últimos diez partidos como máximo; los resultados más recientes se muestran con V y D. Estas cifras no son ratings por posesión.</p>' +
      '<div class="form-columns">' + teamPerformance(game, 'away') + teamPerformance(game, 'home') + '</div>' +
      '<div class="insights-title head-to-head-title">Enfrentamientos anteriores</div>' +
      (list ? '<ul class="head-to-head-list">' + list + '</ul>' :
        '<p class="muted-copy">Sin enfrentamientos anteriores verificados en nuestra ventana de datos.</p>') +
      '<p class="market-note"><strong>Tipo de pronóstico: ganador del partido.</strong> ' +
      'No tenemos aún un modelo validado para hándicaps o diferencias de puntos. ' +
      'No interpretes este porcentaje como posibilidad de cubrir una línea.</p>';
  }
  function historyCard(row) {
    const complete = row.result?.winner === 'home' || row.result?.winner === 'away';
    const home = Number(row.home_pct);
    const away = Number(row.away_pct);
    if (!Number.isFinite(home) || !Number.isFinite(away)) return '';
    const favored = home > away ? 'home' : away > home ? 'away' : 'none';
    const chosenName = favored === 'home' ? row.home : favored === 'away' ? row.away : 'Sin favorito';
    const favoredPct = favored === 'home' ? home : favored === 'away' ? away : 50;
    const correct = complete && favored !== 'none' && favored === row.result.winner;
    const resultTag = !complete ? '<span class="history-result pending">PENDIENTE</span>' :
      favored === 'none' ? '<span class="history-result pending">SIN FAVORITO</span>' :
      correct ? '<span class="history-result hit">ACIERTO</span>' :
      '<span class="history-result miss">FALLO</span>';
    const score = complete && Number.isInteger(row.result.home_score) &&
      Number.isInteger(row.result.away_score) ?
      row.result.away_score + ' - ' + row.result.home_score :
      'Pendiente';
    return '<article class="history-entry">' +
      '<div class="history-meta"><span>' + escapeHtml(row.date || '') + '</span>' +
      resultTag + '</div>' +
      '<div class="history-matchup">' + escapeHtml(row.away || 'Visitante') + ' vs. ' +
      escapeHtml(row.home || 'Local') + '</div>' +
      '<div class="history-forecast">Favorito: <strong>' + escapeHtml(chosenName) + '</strong>' +
      (favored === 'none' ? '' : ' · ' + favoredPct.toFixed(1) + '%') + '</div>' +
      '<div class="history-score">Resultado: <strong>' + score + '</strong></div>' +
      '<div class="history-model">Modelo: ' + escapeHtml(row.model || 'sin versión') + '</div></article>';
  }
  function renderHistory() {
    const list = Array.isArray(data.history_recent) ? data.history_recent : [];
    const safe = list.filter(row => row && row.predicted_at && row.scheduled_at &&
      Date.parse(row.predicted_at) < Date.parse(row.scheduled_at)).slice(0, 45);
    const isFinished = row => row.result && ['home', 'away'].includes(row.result.winner);
    // Mostrar primero los partidos ya evaluados, luego los pendientes:
    // de lo contrario los próximos días pueden desplazar todos los resultados.
    const sorted = safe.slice().sort((a, b) =>
      Number(Boolean(isFinished(b))) - Number(Boolean(isFinished(a))) ||
      (Date.parse(b.scheduled_at) - Date.parse(a.scheduled_at)));
    const filter = activeHistoryFilter;
    const state = row => {
      if (!row.result || !['home', 'away'].includes(row.result.winner)) return 'pending';
      if (row.home_pct === row.away_pct) return 'pending';
      const favorite = row.home_pct > row.away_pct ? 'home' : 'away';
      return row.result.winner === favorite ? 'hit' : 'miss';
    };
    const shown = sorted.filter(row => filter === 'all' ||
      (filter === 'finished' && isFinished(row)) || state(row) === filter).slice(0, 24);
    $('history-count').textContent = shown.length + ' de ' + safe.length;
    $('history-list').innerHTML = shown.length ?
      shown.map(historyCard).join('') :
      '<p class="history-empty">' + (safe.length ? 'No hay pronósticos para este filtro.' :
      'Todavía no tenemos pronósticos anteriores publicados en este registro. ' +
      'Los nuevos partidos quedarán guardados antes del inicio.') + '</p>';
    $('history-filter').innerHTML = [
      ['all','Todos'], ['hit','Acertados'], ['miss','Fallados'], ['pending','Pendientes']
    ].map(([value,label]) => '<button type="button" class="history-pill' +
      (activeHistoryFilter === value ? ' is-active' : '') + '" data-history-filter="' + value +
      '" aria-pressed="' + (activeHistoryFilter === value) + '">' + label + '</button>').join('');
  }

  function gameCard(game) {
    const hasPrediction = validPrediction(game);
    const revision = game.revised_prediction;
    const validRevision = revision &&
      Date.parse(revision.predicted_at) < Date.parse(game.datetime) &&
      Date.parse(revision.predicted_at) > Date.parse(game.prediction?.predicted_at || '1970-01-01') &&
      Number.isFinite(revision.home_pct) && Number.isFinite(revision.away_pct) &&
      revision.home_pct >= 0 && revision.home_pct <= 100 &&
      revision.away_pct >= 0 && revision.away_pct <= 100 &&
      Math.abs(revision.home_pct + revision.away_pct - 100) <= 0.2;
    const p = hasPrediction && validRevision ? revision : game.prediction || {};
    const stateClass = game.status === 'in' ? ' live' : '';
    const hasScore = (game.status === 'in' || game.status === 'post') &&
      Number.isFinite(game.home_score) && Number.isFinite(game.away_score);
    const teamMark = (side) => {
      const t = game[side] || {};
      return '<div class="team-mark">' +
        '<img loading="lazy" src="' + escapeHtml(logoFor(t)) + '" alt="" />' +
        '<span>' + escapeHtml(t.abbr || 'NBA') + '</span></div>';
    };
    const teamName = (side) => {
      const t = game[side] || {};
      return '<div class="team-identity ' + side + '">' +
        '<span class="team-abbr">' + escapeHtml(t.abbr || 'NBA') + '</span>' +
        '<span class="team-full-name">' + escapeHtml(t.name || 'Equipo por confirmar') + '</span>' +
      '</div>';
    };
    let percentageBar = '<div class="probability-unavailable">Porcentajes no disponibles</div>';
    let verdict = '<span class="outcome-chip neutral">SIN PRONÓSTICO</span>';
    if (hasPrediction) {
      const away = Number(p.away_pct);
      const home = Number(p.home_pct);
      const close = Math.abs(away-home) <= 10;
      const leftColor = close ? '#666a72' : '#125497';
      const rightColor = close ? '#cd2347' : '#f8bc37';
      percentageBar = '<div class="probability-track" role="img" aria-label="' +
        escapeHtml(game.away?.name || '') + ': ' + formatPct(away) +
        ' por ciento; ' + escapeHtml(game.home?.name || '') + ': ' +
        formatPct(home) + ' por ciento">' +
        '<div class="probability-segment" style="width:' + formatPct(away) + '%;background:' +
        leftColor + '"><span class="probabilidad ' + probabilityTone(away) + '">' + Math.round(away) + '%</span></div>' +
        '<div class="probability-segment" style="width:' + formatPct(home) + '%;background:' +
        rightColor + '"><span class="probabilidad ' + probabilityTone(home) + '">' + Math.round(home) + '%</span></div>' +
      '</div>';
      const diff = Math.abs(away - home);
      const verdictText = diff >= 20 ? 'ALTA PROBABILIDAD' :
        diff <= 10 ? 'PARTIDO DISPUTADO' : 'VENTAJA MODERADA';
      const verdictClass = diff >= 20 ? 'high' : diff <= 10 ? 'close' : 'neutral';
      const reason = shortReason(game,true);
      verdict = '<span class="outcome-chip ' + verdictClass + '" title="' +
        escapeHtml(reason) + '">' + verdictText + '</span>';
      if (game.status === 'in' || game.status === 'post') {
        verdict += '<span class="pre-match-flag" title="Pronóstico ANTES del partido, no probabilidad en vivo.">PRONÓSTICO PREPARTIDO</span>';
      }
    } else {
      verdict = '<span class="outcome-chip neutral" title="' +
        escapeHtml(shortReason(game,false)) + '">SIN PRONÓSTICO</span>';
    }
    const scoreboard = hasScore ?
      '<div class="scoreline" aria-label="Marcador: ' +
      escapeHtml(game.away?.name || 'Visitante') + ' ' + game.away_score + ', ' +
      escapeHtml(game.home?.name || 'Local') + ' ' + game.home_score + '">' +
      '<strong class="live-score">' + game.away_score + '</strong><span>MARCADOR</span>' +
      '<strong class="live-score">' + game.home_score + '</strong></div>' : '';
    const id=escapeHtml(String(game.id || ''));
    return '<details class="game-card" data-game-id="' + id + '"' +
      (expandedGameId === String(game.id) ? ' open' : '') + '>' +
      '<summary class="game-summary" data-game-id="' + id + '">' +
      '<div class="game-top">' + teamMark('away') +
      '<div class="game-center"><span class="game-time">' +
        escapeHtml(timeLabel(game.datetime)) + ' · RD</span>' +
        '<span class="game-state' + stateClass + '">' +
        escapeHtml(stateLabel(game)) + '</span></div>' +
      teamMark('home') + '</div>' +
      '<div class="matchup">' + teamName('away') + teamName('home') + '</div>' +
      scoreboard + percentageBar +
      (hasPrediction && validRevision ?
        '<div class="revision-note"><strong>ACTUALIZADO PREPARTIDO · ' +
        escapeHtml(timeLabel(revision.predicted_at)) + ' RD</strong>' +
        '<span>Primera predicción: ' +
        escapeHtml(game.away?.abbr || 'VIS') + ' ' + formatPct(game.prediction.away_pct) +
        '% · ' + escapeHtml(game.home?.abbr || 'LOC') + ' ' +
        formatPct(game.prediction.home_pct) +
        '%</span><span>Recalculado con resultados previos. La predicción original permanece en el historial.</span></div>' :
        '') +
      '<div class="game-bottom">' + verdict +
      (game.historical ? '<span class="pre-match-flag">ARCHIVO · RESULTADO VERIFICADO CUANDO ESTÉ DISPONIBLE</span>' : '') +
      '</div>' +
      '<span class="expand-hint">Ver jugadores y titulares <span class="expand-arrow" aria-hidden="true">⌄</span></span></summary>' +
      '<div class="game-breakdown">' +
      (game.historical ?
        '<p class="archive-note">Este es un partido histórico. Solo se muestran porcentajes prepartido si se guardaron antes del inicio. ' +
        'No presentamos forma actual ni titulares como si fueran datos del pasado.</p>' :
        matchupInsights(game) + playersPanel(game) + contextPanel(game)) +
      (game.source ? '<a class="game-link" href="' + escapeHtml(game.source) +
        '" target="_blank" rel="noopener noreferrer">Ficha del partido en ESPN ↗</a>' : '') +
      '</div></details>';
  }
  function renderDates(games) {
    const dates = [...new Set(games.map(g => g.date).filter(d => /^\d{4}-\d{2}-\d{2}$/.test(d)))].sort();
    if (!dates.includes(chosenDate)) chosenDate = dates.find(d => d >= todayInRD()) || dates[dates.length-1] || todayInRD();
    $('date-tabs').innerHTML = dates.map(date =>
      `<button type="button" data-date="${escapeHtml(date)}" aria-current="${date === chosenDate ? 'date' : 'false'}">${escapeHtml(dateLabel(date))}</button>`
    ).join('');
    $('date-tabs').querySelectorAll('button').forEach(button => {
      button.addEventListener('click', () => {
        chosenDate = button.dataset.date;
        render();
        refreshLive();
      });
    });
  }

  function renderCalibration() {
    const metrics = data.validation || {};
    const bins = Array.isArray(metrics.calibration) ? metrics.calibration : [];
    const rows = bins.filter(row => row && Number.isInteger(row.count) && row.count > 0 &&
      Number.isFinite(row.average_predicted_pct) && Number.isFinite(row.actual_home_win_pct) &&
      row.average_predicted_pct >= 0 && row.average_predicted_pct <= 100 &&
      row.actual_home_win_pct >= 0 && row.actual_home_win_pct <= 100);
    $('calibration-chart').innerHTML = rows.length ? rows.map(row =>
      '<div class="calibration-row">' +
      '<div class="calibration-meta"><strong>' + escapeHtml(row.range || '') +
      '</strong><span>' + row.count + ' partidos</span></div>' +
      '<div class="calibration-metric"><span>Previsto</span><div class="calibration-track">' +
      '<div class="calibration-fill expected" style="width:' + row.average_predicted_pct + '%"></div>' +
      '</div><b>' + row.average_predicted_pct.toFixed(1) + '%</b></div>' +
      '<div class="calibration-metric"><span>Real</span><div class="calibration-track">' +
      '<div class="calibration-fill observed" style="width:' + row.actual_home_win_pct + '%"></div>' +
      '</div><b>' + row.actual_home_win_pct.toFixed(1) + '%</b></div></div>'
    ).join('') : '<p class="history-empty">Aún no hay resultados suficientes para dibujar la calibración.</p>';
    const models = metrics.by_model && typeof metrics.by_model === 'object' ? metrics.by_model : {};
    const keys = Object.keys(models).slice(0, 8);
    $('model-versions').innerHTML = keys.length ?
      '<h3>Rendimiento por versión del modelo</h3><div class="model-version-list">' +
      keys.map(name => {
        const entry = models[name] || {};
        return Number.isInteger(entry.n) && Number.isFinite(entry.brier) ?
          '<div class="model-version"><strong>' + escapeHtml(name) +
          '</strong><span>' + entry.n + ' partidos</span><b>Brier ' +
          entry.brier.toFixed(4) + '</b></div>' : '';
      }).join('') + '</div>' : '';
    const quality = data.data_quality || {};
    const missing = Number.isInteger(quality.missing_historical_days) ? quality.missing_historical_days : 0;
    $('data-health').textContent = quality.history_partial ?
      'Advertencia: ESPN no respondió en ' + missing +
      ' fechas históricas de esta actualización. Las métricas solo usan partidos confirmados; la información histórica puede estar incompleta.' :
      'Origen de resultados: ESPN (API no oficial). Los marcadores pueden retrasarse y las probabilidades son experimentales.';
    $('data-health').className = 'data-health' + (quality.history_partial ? ' health-warning' : '');
  }


  function renderScouting() {
    const games = Array.isArray(data.games) ? data.games : [];
    const dayGames = games.filter(g => g.date === chosenDate &&
      g.scouting && g.prediction && validPrediction(g)).sort((a,b) =>
        String(a.datetime).localeCompare(String(b.datetime)));
    const fmt = n => Number.isFinite(n) ? n.toFixed(1) : '—';
    const side = (team, form) => {
      const wins = Number.isInteger(form?.wins) ? form.wins : null;
      const played = Number.isInteger(form?.games) ? form.games : 0;
      return '<div class="scout-team"><strong>' + escapeHtml(team?.name || 'Equipo') +
        '</strong><span>' + (wins === null || !played ? 'Récord por verificar' :
        wins + ' victorias en ' + played + ' juegos') + '</span>' +
        '<span>Margen reciente: ' + fmt(form?.margin) + '</span></div>';
    };
    $('scouting-games').innerHTML = dayGames.length ? dayGames.map(g => {
      const sc = g.scouting;
      const notes = Array.isArray(sc.observations) ? sc.observations.slice(0, 3) : [];
      const updated = !!g.revised_prediction &&
        Number.isFinite(g.revised_prediction.home_pct) &&
        Number.isFinite(g.revised_prediction.away_pct) &&
        Date.parse(g.revised_prediction.predicted_at) < Date.parse(g.datetime);
      const predictionName = String(sc.favorite || 'Sin favorito claro');
      const pct = Number(sc.favorite_pct_original);
      const forecaster = Number.isFinite(pct) && pct >= 50 && pct <= 100 ?
        pct.toFixed(1) + '%' : '—';
      return '<article class="scout-card">' +
        '<div class="scout-top"><span>' + escapeHtml(timeLabel(g.datetime)) +
        ' · RD</span><span>ANÁLISIS DESCRIPTIVO</span></div>' +
        '<div class="scout-matchup">' + escapeHtml(g.away?.name || '') + ' <span>vs.</span> ' +
        escapeHtml(g.home?.name || '') + '</div>' +
        '<div class="scout-forecast"><span>' + (updated ? 'Favorito del pronóstico actualizado' : 'Favorito del pronóstico original') + '</span>' +
        '<strong>' + escapeHtml(predictionName) + ' · ' + forecaster + '</strong></div>' +
        '<div class="scout-rating">' + escapeHtml(sc.classification || 'Por comprobar') + '</div>' +
        '<div class="scout-teams">' + side(g.away,sc.away_form) + side(g.home,sc.home_form) + '</div>' +
        '<ul class="scout-notes">' + notes.map(note=>'<li>' + escapeHtml(note) + '</li>').join('') +
        '</ul><p class="scout-footer">' + (updated ?
        'Revisión registrada antes del inicio · predicción original preservada' :
        'Diagnóstico nuevo · predicción original preservada') + '</p>' +
        '</article>';
    }).join('') :
      '<p class="history-empty">Análisis descriptivo todavía no disponible para esta fecha. ' +
      'Se publicará cuando termine la actualización de datos verificados.</p>';
  }

  function renderValidation() {
    const metrics = data.validation || {};
    const n = Number.isInteger(metrics.completed_predictions) && metrics.completed_predictions >= 0 ?
      metrics.completed_predictions : 0;
    const pct = n && Number.isFinite(metrics.favorite_accuracy_pct) &&
      metrics.favorite_accuracy_pct >= 0 && metrics.favorite_accuracy_pct <= 100 ?
      metrics.favorite_accuracy_pct.toFixed(1) + '%' : '—';
    const brier = n && Number.isFinite(metrics.brier_score) &&
      metrics.brier_score >= 0 && metrics.brier_score <= 1 ?
      metrics.brier_score.toFixed(4) : '—';
    const logLoss = n && Number.isFinite(metrics.log_loss) && metrics.log_loss >= 0 ?
      metrics.log_loss.toFixed(4) : '—';
    const card = (name, value, subtitle, extra = '') =>
      '<div class="quality-metric"><span class="metric-name">' + name + '</span>' +
      '<strong class="metric-value">' + value + '</strong>' +
      extra +
      '<span class="metric-hint">' + subtitle + '</span></div>';
    const accuracy = n && Number.isFinite(metrics.favorite_accuracy_pct) &&
      metrics.favorite_accuracy_pct >= 0 && metrics.favorite_accuracy_pct <= 100 ?
      metrics.favorite_accuracy_pct : null;
    const accuracyVisual = accuracy === null ? '' :
      '<div class="accuracy-bar" role="img" aria-label="Acierto ' + accuracy.toFixed(1) +
      ' por ciento; fallos ' + (100-accuracy).toFixed(1) + ' por ciento">' +
      '<span class="accuracy-hit" style="width:' + accuracy + '%"></span>' +
      '<span class="accuracy-miss" style="width:' + (100-accuracy) + '%"></span></div>' +
      '<span class="accuracy-legend"><span>Acertados ' + accuracy.toFixed(1) +
      '%</span><span>Fallados ' + (100-accuracy).toFixed(1) + '%</span></span>';
    $('model-validation').innerHTML =
      card('Partidos evaluados', String(n), 'Pronósticos registrados antes del juego') +
      card('Acierto del favorito', pct, 'Porcentaje de ganadores identificados', accuracyVisual) +
      card('Error Brier', brier, 'Menor es mejor · referencia 50/50: 0.2500') +
      card('Log loss', logLoss, 'Penaliza probabilidades demasiado seguras');
    $('quality-caveat').textContent = n === 0 ?
      'Todavía no hay partidos finalizados con pronóstico evaluado. No podemos afirmar que el modelo acierta.' :
      n < 100 ? 'Muestra inicial de ' + n + ' partidos: estos resultados pueden variar mucho. Necesitamos una muestra mayor y revisar la calibración.' :
      'Resultados históricos del modelo. Un buen porcentaje de aciertos no demuestra por sí solo que las probabilidades estén calibradas.';
    const comparison = metrics.elo_comparison || {};
    const paired = Number.isInteger(comparison.n) ? comparison.n : 0;
    $('elo-validation').innerHTML = paired > 0 &&
      Number.isFinite(comparison.model_brier) && Number.isFinite(comparison.elo_brier) ?
      '<strong>Modelo NBA Analytics frente a Elo simple</strong>' +
      '<p>Comparación en exactamente ' + paired + ' partidos con pronósticos previos. ' +
      'Brier de nuestro modelo: <b>' + comparison.model_brier.toFixed(4) +
      '</b> · Brier Elo: <b>' + comparison.elo_brier.toFixed(4) + '</b>. ' +
      'Menor indica menos error. No demuestra ventaja si la muestra es pequeña.</p>' :
      '<strong>Comparación con Elo simple</strong>' +
      '<p>Aún no hay resultados suficientes con ambas predicciones prepartido para comparar los modelos.</p>';
  }
  function render() {
    const games = Array.isArray(data.games) ? data.games : [];
    renderDates(games);
    const shown = games.filter(g => g.date === chosenDate).sort((a, b) => String(a.datetime).localeCompare(String(b.datetime)));
    $('game-count').textContent = shown.length + (shown.length === 1 ? ' partido' : ' partidos');
    const ts = Date.parse(data.as_of || '');
    const reported = Number.isFinite(ts) ?
      new Intl.DateTimeFormat('es-DO', {timeZone: zone, day:'numeric', month:'short', hour:'numeric', minute:'2-digit'}).format(new Date(ts)) :
      'sin actualizar';
    const liveTime = liveUpdatedAt ?
      new Intl.DateTimeFormat('es-DO', {timeZone: zone, hour:'numeric', minute:'2-digit', second:'2-digit'}).format(new Date(liveUpdatedAt)) : '';
    $('updated').textContent = liveAvailable ?
      'Marcadores ESPN: ' + liveTime + ' · Pronósticos: ' + reported :
      'Pronósticos: ' + reported;
    $('games').innerHTML = shown.length ? shown.map(gameCard).join('') :
      '<div class="empty-state">No hay partidos publicados para esta fecha.</div>';
    renderNews();
    renderScouting();
    renderValidation();
    renderCalibration();
    renderHistory();
    if (liveError && !liveAvailable) {
      setStatus('No fue posible conectar con el marcador de ESPN. Se muestran los últimos datos publicados.', 'warning');
    } else if (liveError || (liveAvailable && Date.now() - liveUpdatedAt > 120000)) {
      setStatus('La fuente ha interrumpido o limitado las consultas. Reintentando gradualmente; marcadores no necesariamente actuales.', 'warning');
    } else if (liveAvailable) {
      setStatus(hasLiveGameOnScreen() ?
        'En vivo: comprobando ESPN cada 2 segundos si permite el acceso. Los datos pueden llegar con retraso.' :
        'Los marcadores se consultan cada 30 segundos fuera de los partidos. El pronóstico es prepartido.', 'ok');
    } else if (loadError || !isFresh()) {
      setStatus('Esperando datos recientes. No mostramos porcentajes desactualizados.', 'warning');
    } else {
      setStatus('Pronósticos preparados. Consultando los resultados en vivo de ESPN…', 'ok');
    }
  }
  function setStatus(message, type) {
    $('alert').textContent = message;
    $('alert').className = 'status-message ' + (type || '');
  }
  async function load() {
    const button = $('reload');
    button.disabled = true;
    try {
      if (typeof location !== 'undefined' && location.protocol === 'file:') {
        throw new Error('La actualización necesita una página web publicada.');
      }
      const response = await fetch('data/latest.json?ts=' + Date.now(), {cache:'no-store'});
      if (!response.ok) throw new Error('HTTP ' + response.status);
      const incoming = await response.json();
      if (!incoming || !Array.isArray(incoming.games)) throw new Error('Formato de datos incorrecto');
      data = incoming;
      loadError = false;
    } catch (error) {
      loadError = true;
    } finally {
      button.disabled = false;
      render();
    }
  }
  function parseScore(value) {
    if (value === '' || value === undefined || value === null) return null;
    const score = Number(value);
    return Number.isFinite(score) && score >= 0 ? Math.floor(score) : null;
  }
  function localDate(iso) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(new Date(iso));
    const value = k => parts.find(p => p.type === k)?.value || '';
    return value('year') + '-' + value('month') + '-' + value('day');
  }
  function parseLiveEvent(event) {
    try {
      const competitors = event.competitions[0].competitors;
      const h = competitors.find(c => c.homeAway === 'home');
      const a = competitors.find(c => c.homeAway === 'away');
      if (!h?.team || !a?.team || !event.id || !event.date) return null;
      const team = c => ({
        id: String(c.team.id || ''),
        abbr: String(c.team.abbreviation || ''),
        name: String(c.team.displayName || c.team.shortDisplayName || c.team.name || 'Equipo')
      });
      const state = event.status?.type?.state;
      const status = ['pre', 'in', 'post'].includes(state) ? state : 'pre';
      const detail = String(event.status?.type?.shortDetail || event.status?.type?.detail || '').slice(0, 45);
      return {
        id: String(event.id), date: localDate(event.date), datetime: event.date,
        home: team(h), away: team(a), status,
        home_score: status === 'pre' ? null : parseScore(h.score),
        away_score: status === 'pre' ? null : parseScore(a.score),
        status_detail: detail,
        source: 'https://www.espn.com/nba/game/_/gameId/' + encodeURIComponent(String(event.id))
      };
    } catch (e) { return null; }
  }
  let liveRequestNumber = 0;
  async function refreshLive() {
    if (livePollInFlight) return;
    livePollInFlight = true;
    lastLivePollStarted = Date.now();
    const request = ++liveRequestNumber;
    const date = chosenDate;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
    try {
      const url = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=' +
        date.replace(/-/g, '') + '&limit=100';
      const response = await fetch(url, {cache: 'no-store'});
      if (!response.ok) {
        if ([403, 429, 503].includes(response.status)) nextLiveRetryAt = Date.now() + 60000;
        throw new Error('ESPN ' + response.status);
      }
      const scoreboard = await response.json();
      if (!Array.isArray(scoreboard.events)) throw new Error('Respuesta ESPN inválida');
      if (request !== liveRequestNumber || date !== chosenDate) return;
      const parsed = scoreboard.events.map(parseLiveEvent).filter(Boolean);
      if (scoreboard.events.length && !parsed.length) throw new Error('No se pudieron interpretar los eventos');
      const old = new Map((data.games || []).map(g => [String(g.id), g]));
      const merged = new Map((data.games || []).filter(g => g.date !== date).map(g => [String(g.id), g]));
      for (const g of parsed) {
        const prior = old.get(g.id) || {};
        merged.set(g.id, {...prior, ...g, prediction: prior.prediction || null});
      }
      data = {...data, games: Array.from(merged.values())};
      liveAvailable = true;
      liveError = false;
      liveUpdatedAt = Date.now();
      liveFailures = 0;
      nextLiveRetryAt = 0;
    } catch (e) {
      if (request !== liveRequestNumber) return;
      liveError = true;
      liveFailures += 1;
      // Evitar insistir cada dos segundos si hay fallos o límites de peticiones.
      nextLiveRetryAt = Math.max(nextLiveRetryAt,
        Date.now() + Math.min(60000, 5000 * Math.pow(2, Math.min(4, liveFailures - 1))));
    } finally {
      livePollInFlight = false;
    }
    render();
  }
  $('games').addEventListener('click', event => {
    const summary=event.target?.closest?.('summary.game-summary');
    if (!summary) return;
    event.preventDefault();
    const id=String(summary.dataset.gameId || '');
    if (!id) return;
    expandedGameId=expandedGameId === id ? '' : id;
    render();
    if (expandedGameId === id) fetchGameSummary(id);
  });
  $('reload').addEventListener('click', async () => { await load(); await refreshLive(); });
  $('history-filter').addEventListener('click', event => {
    const button = event.target?.closest?.('button[data-history-filter]');
    const filter = button?.dataset?.historyFilter;
    if (!['all','hit','miss','pending'].includes(filter)) return;
    activeHistoryFilter = filter;
    renderHistory();
  });
  const backToTop = $('back-to-top');
  function updateBackToTop() {
    const scrollY = typeof window === 'undefined' ? 0 :
      (window.scrollY || document.documentElement?.scrollTop || 0);
    backToTop.classList.toggle('visible', scrollY > 360);
  }
  backToTop.addEventListener('click', () => {
    if (typeof window === 'undefined') return;
    const reducedMotion = typeof matchMedia === 'function' &&
      matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.scrollTo({top: 0, behavior: reducedMotion ? 'auto' : 'smooth'});
  });
  if (typeof window !== 'undefined') {
    window.addEventListener('scroll', updateBackToTop, {passive: true});
  }
  updateBackToTop();
  (async () => { await load(); await refreshLive(); })();
  function hasLiveGameOnScreen() {
    return Array.isArray(data.games) &&
      data.games.some(g => g.date === chosenDate && g.status === 'in');
  }
  function pollVisibleGames() {
    if (typeof document.visibilityState !== 'undefined' && document.visibilityState === 'hidden') return;
    const now = Date.now();
    const active = hasLiveGameOnScreen();
    const interval = active ? LIVE_INTERVAL_MS : IDLE_INTERVAL_MS;
    if (now >= nextLiveRetryAt && !livePollInFlight && now - lastLivePollStarted >= interval) {
      refreshLive();
    }
    if (active && expandedGameId && now - lastPlayersPollStarted >= PLAYER_INTERVAL_MS) {
      const selected = (data.games || []).find(g => String(g.id) === expandedGameId);
      if (selected?.status === 'in') {
        lastPlayersPollStarted = now;
        fetchGameSummary(expandedGameId);
      }
    }
  }
  if (typeof setInterval === 'function') {
    setInterval(pollVisibleGames, LIVE_INTERVAL_MS);
  }
})();
