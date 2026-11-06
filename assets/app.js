'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c =>
    ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const zone = 'America/Santo_Domingo';
  const seed = JSON.parse($('seed').textContent);
  let data = seed;
  let chosenDate = '';
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

  function scoreSourceUrl(date) {
    return /^\d{4}-\d{2}-\d{2}$/.test(date || '') ?
      'https://www.thescore.com/nba/events/' + date : 'https://www.thescore.com/nba';
  }
  function gameCard(game) {
    const hasPrediction = validPrediction(game);
    const p = game.prediction || {};
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
        leftColor + '"><span>' + Math.round(away) + '%</span></div>' +
        '<div class="probability-segment" style="width:' + formatPct(home) + '%;background:' +
        rightColor + '"><span>' + Math.round(home) + '%</span></div>' +
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
      '<div class="game-bottom">' + verdict + '</div>' +
      '<span class="expand-hint">Ver jugadores y titulares <span class="expand-arrow" aria-hidden="true">⌄</span></span></summary>' +
      '<div class="game-breakdown">' + playersPanel(game) +
      '<div class="source-links">' +
      (game.source ? '<a class="game-link" href="' + escapeHtml(game.source) +
        '" target="_blank" rel="noopener noreferrer">Consultar partido en ESPN ↗</a>' : '') +
      '<a class="game-link" href="' + escapeHtml(scoreSourceUrl(game.date)) +
        '" target="_blank" rel="noopener noreferrer">Comparar jornada en theScore ↗</a>' +
      '</div></div></details>';
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
  function render() {
    const games = Array.isArray(data.games) ? data.games : [];
    renderDates(games);
    $('thescore-link').href = scoreSourceUrl(chosenDate);
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
