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
    if (!isFresh() || game.status !== 'pre' ||
        !(Date.parse(game.datetime) > Date.now()) ||
        !p || !Number.isFinite(p.home_pct) || !Number.isFinite(p.away_pct)) return false;
    return p.home_pct >= 0 && p.away_pct >= 0 &&
      p.home_pct <= 100 && p.away_pct <= 100 &&
      Math.abs(p.home_pct + p.away_pct - 100) <= 0.2;
  }
  function formatPct(n) {
    return Number(n).toFixed(1);
  }
  function stateLabel(game) {
    if (game.status === 'post') return 'FINALIZADO';
    if (game.status === 'in' || (Date.parse(game.datetime) <= Date.now())) return 'EN JUEGO / PENDIENTE';
    return 'PROGRAMADO';
  }
  function shortReason(game, allowed) {
    if (!allowed) {
      if (game.status === 'post') return 'El partido finalizó. No publicamos pronósticos retrospectivos.';
      if (game.status === 'in' || Date.parse(game.datetime) <= Date.now()) return 'El encuentro ya comenzó. Sin pronóstico nuevo.';
      if (!isFresh()) return 'Datos sin actualizar; porcentajes ocultos para evitar errores.';
      return 'Todavía no hay datos suficientes para estimar el resultado.';
    }
    const reason = game.prediction?.reason;
    return typeof reason === 'string' && reason.trim() ? reason.slice(0, 150) :
      'Ventaja estimada por forma reciente, rendimiento y localía.';
  }
  function gameCard(game) {
    const hasPrediction = validPrediction(game);
    const p = game.prediction || {};
    const favoredSide = hasPrediction && Math.abs(p.home_pct - p.away_pct) >= 0.2 ? (p.home_pct > p.away_pct ? 'home' : 'away') : '';
    const team = side => {
      const t = game[side] || {};
      const pct = hasPrediction ? (side === 'home' ? p.home_pct : p.away_pct) : null;
      const favorite = favoredSide === side;
      return `<div class="team ${favorite ? 'favorite' : ''}">
        <span class="team-abbr">${escapeHtml(t.abbr || 'NBA')}</span>
        <span class="team-name">${escapeHtml(t.name || 'Equipo por confirmar')}</span>
        <span class="prob" aria-label="${hasPrediction ? 'Probabilidad de ' + escapeHtml(t.name) + ': ' + formatPct(pct) + ' por ciento' : 'Probabilidad sin publicar'}">${hasPrediction ? formatPct(pct) : '—'}${hasPrediction ? '<span>%</span>' : ''}</span>
        <span class="favorite-label">${favorite ? 'MÁS PROBABLE' : ' '}</span>
      </div>`;
    };
    const split = hasPrediction ? `<div class="split-bar" role="img" aria-label="${escapeHtml(game.away?.name)} ${formatPct(p.away_pct)}%, ${escapeHtml(game.home?.name)} ${formatPct(p.home_pct)}%"><span style="width:${formatPct(p.away_pct)}%"></span></div>` : '';
    return `<article class="game-card">
      <div class="game-top"><span class="game-time">${escapeHtml(timeLabel(game.datetime))} · RD</span><span class="game-state">${escapeHtml(stateLabel(game))}</span></div>
      <div class="matchup">${team('away')}${team('home')}</div>
      ${split}
      <p class="card-reason"><span class="reason-label">Por qué:</span> ${escapeHtml(shortReason(game, hasPrediction))}</p>
    </article>`;
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
      });
    });
  }
  function render() {
    const games = Array.isArray(data.games) ? data.games : [];
    renderDates(games);
    const shown = games.filter(g => g.date === chosenDate).sort((a, b) => String(a.datetime).localeCompare(String(b.datetime)));
    $('game-count').textContent = shown.length + (shown.length === 1 ? ' partido' : ' partidos');
    const ts = Date.parse(data.as_of || '');
    $('updated').textContent = Number.isFinite(ts) ?
      'Actualizado ' + new Intl.DateTimeFormat('es-DO', {timeZone: zone, day:'numeric', month:'short', hour:'numeric', minute:'2-digit'}).format(new Date(ts)) + ' · RD' :
      'Sin datos publicados';
    $('games').innerHTML = shown.length ? shown.map(gameCard).join('') :
      '<div class="empty-state">No hay partidos publicados para esta fecha.</div>';
    if (loadError) setStatus('No se pudo actualizar. Comprueba la conexión o inténtalo más tarde.', 'warning');
    else if (!isFresh()) setStatus('El informe aún no está actualizado. No mostramos porcentajes desfasados.', 'warning');
    else setStatus('Pronósticos experimentales actualizados. Las probabilidades pueden cambiar antes del partido.', 'ok');
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
  $('reload').addEventListener('click', load);
  load();
})();
