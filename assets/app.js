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
  const LIVE_INTERVAL_MS = 30000;

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
    return '<article class="game-card">' +
      '<div class="game-top">' + teamMark('away') +
      '<div class="game-center"><span class="game-time">' +
        escapeHtml(timeLabel(game.datetime)) + ' · RD</span>' +
        '<span class="game-state' + stateClass + '">' +
        escapeHtml(stateLabel(game)) + '</span></div>' +
      teamMark('home') + '</div>' +
      '<div class="matchup">' + teamName('away') + teamName('home') + '</div>' +
      scoreboard + percentageBar +
      '<div class="game-bottom">' + verdict + '</div>' +
      (game.source ? '<a class="game-link" href="' + escapeHtml(game.source) +
        '" target="_blank" rel="noopener noreferrer">Ver en ESPN</a>' : '') +
    '</article>';
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
    const shown = games.filter(g => g.date === chosenDate).sort((a, b) => String(a.datetime).localeCompare(String(b.datetime)));
    $('game-count').textContent = shown.length + (shown.length === 1 ? ' partido' : ' partidos');
    const ts = Date.parse(data.as_of || '');
    const reported = Number.isFinite(ts) ?
      new Intl.DateTimeFormat('es-DO', {timeZone: zone, day:'numeric', month:'short', hour:'numeric', minute:'2-digit'}).format(new Date(ts)) :
      'sin actualizar';
    const liveTime = liveUpdatedAt ?
      new Intl.DateTimeFormat('es-DO', {timeZone: zone, hour:'numeric', minute:'2-digit'}).format(new Date(liveUpdatedAt)) : '';
    $('updated').textContent = liveAvailable ?
      'Marcadores ESPN: ' + liveTime + ' · Pronósticos: ' + reported :
      'Pronósticos: ' + reported;
    $('games').innerHTML = shown.length ? shown.map(gameCard).join('') :
      '<div class="empty-state">No hay partidos publicados para esta fecha.</div>';
    if (liveError && !liveAvailable) {
      setStatus('No fue posible conectar con el marcador de ESPN. Se muestran los últimos datos publicados.', 'warning');
    } else if (liveError || (liveAvailable && Date.now() - liveUpdatedAt > 120000)) {
      setStatus('Conexión de marcadores interrumpida; estos resultados pueden estar atrasados.', 'warning');
    } else if (liveAvailable) {
      setStatus('Marcadores consultados en ESPN cada 30 segundos. Los porcentajes son pronósticos ANTES del partido, no en vivo.', 'ok');
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
    const request = ++liveRequestNumber;
    const date = chosenDate;
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
    try {
      const url = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=' +
        date.replace(/-/g, '') + '&limit=100';
      const response = await fetch(url, {cache: 'no-store'});
      if (!response.ok) throw new Error('ESPN ' + response.status);
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
    } catch (e) {
      if (request !== liveRequestNumber) return;
      liveError = true;
    }
    render();
  }
  $('reload').addEventListener('click', async () => { await load(); await refreshLive(); });
  (async () => { await load(); await refreshLive(); })();
  if (typeof setInterval === 'function') {
    setInterval(() => {
      if (typeof document.visibilityState === 'undefined' || document.visibilityState !== 'hidden') refreshLive();
    }, LIVE_INTERVAL_MS);
  }
})();
