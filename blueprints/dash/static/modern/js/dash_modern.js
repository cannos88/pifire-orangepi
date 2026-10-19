/*
 * Modern dashboard (Ember) for PiFire.
 *
 * Live values:   GET /api/current every 2 s
 * Chart/timer:   GET /dash/modern/data?minutes=N every 15 s (and after timer commands)
 * Commands:      POST /api/set/...  (same API the other dashboards and MQTT use)
 */
(function () {
	'use strict';

	var CFG = JSON.parse(document.getElementById('mdConfig').textContent);
	var UNITS = CFG.units === 'F' ? 'F' : 'C';
	var LIMITS = UNITS === 'C' ? { min: 65, max: 260, step: 5 } : { min: 150, max: 500, step: 5 };
	var FAST_MS = 2000, SLOW_MS = 15000, OFFLINE_AFTER = 4;
	var HOLD_DEBOUNCE_MS = 1300, LOCAL_WINS_MS = 5000;
	var READY_MARGIN = UNITS === 'C' ? 5 : 10;  // a reached probe stays "PRONTO" until it cools this much

	var MODE_IT = {
		Stop: 'Spento', Startup: 'Accensione', Reignite: 'Riaccensione', Smoke: 'Affumicatura',
		Hold: 'Mantenimento', Shutdown: 'Spegnimento', Monitor: 'Monitoraggio', Prime: 'Caricamento pellet',
		Manual: 'Manuale', Recipe: 'Ricetta', Error: 'Errore'
	};
	var FIRE_MODES = ['Startup', 'Reignite', 'Smoke', 'Hold', 'Recipe', 'Manual'];
	var DEFAULT_PRESETS = UNITS === 'C'
		? [['Affumicatura', 90], ['Low & slow', 110], ['Arrosto', 180], ['Rosolatura', 230]]
		: [['Affumicatura', 195], ['Low & slow', 225], ['Arrosto', 350], ['Rosolatura', 450]];
	var FOOD_PRESETS = UNITS === 'C'
		? [['Manzo al sangue', 54], ['Maiale', 63], ['Pollo', 74], ['Pulled pork', 93]]
		: [['Manzo al sangue', 130], ['Maiale', 145], ['Pollo', 165], ['Pulled pork', 200]];

	var $ = function (id) { return document.getElementById(id); };
	var probes = CFG.probes || [];
	var primary = CFG.primary;
	var foodProbes = probes.filter(function (p) { return p.group === 'F'; });

	var state = {
		cur: null,            // last /api/current
		data: null,           // last /dash/modern/data
		dataAt: 0,            // when it arrived (ms)
		minutes: parseInt(CFG.chart_minutes, 10) || 90,
		errors: 0,
		uiHash: null,
		pendingTarget: null,  // stepper value not yet sent
		localTarget: null,    // value sent, shown until the server agrees
		localTargetUntil: 0,
		localSplus: null,
		localSplusUntil: 0,
		lastHoldTarget: null,
		timerDoneAt: 0,       // end time of a timer that expired while the page was open
		holdTimer: null,
		probeDialogLabel: null,
		serverOffset: 0       // server time - browser time (s)
	};

	/* ------------------------------------------------------------ helpers */

	function now() { return Date.now() / 1000 + state.serverOffset; }

	function fmtTemp(v) {
		if (v === null || v === undefined || isNaN(v)) { return '—'; }
		return String(Math.round(v));
	}

	function fmtDuration(seconds, withSeconds) {
		seconds = Math.max(0, Math.round(seconds));
		var h = Math.floor(seconds / 3600), m = Math.floor((seconds % 3600) / 60), s = seconds % 60;
		if (withSeconds) {
			var mm = (h ? String(m).padStart(2, '0') : String(m));
			return (h ? h + ':' : '') + mm + ':' + String(s).padStart(2, '0');
		}
		if (h) { return h + ' h ' + m + ' min'; }
		return m + ' min';
	}

	function clockTime(epoch) {
		var d = new Date((epoch - state.serverOffset) * 1000);
		return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
	}

	function clampTarget(v) {
		return Math.max(LIMITS.min, Math.min(LIMITS.max, Math.round(v)));
	}

	function setText(el, text) { if (el && el.textContent !== text) { el.textContent = text; } }
	function show(el, visible) { if (el) { el.hidden = !visible; } }

	function toast(message, isError) {
		var el = $('toast');
		el.textContent = message;
		el.classList.toggle('is-error', !!isError);
		el.hidden = false;
		clearTimeout(toast._t);
		toast._t = setTimeout(function () { el.hidden = true; }, 3500);
	}

	function api(path) {
		return fetch('/api/set/' + path, { method: 'POST' })
			.then(function (r) { return r.json(); })
			.then(function (res) {
				if (res && res.result && res.result !== 'OK') {
					toast(res.message || 'Comando rifiutato', true);
					throw new Error(res.message);
				}
				return res;
			})
			.catch(function (err) {
				if (!(err instanceof Error && err.message)) { toast('Comando non inviato: il grill non risponde', true); }
				throw err;
			});
	}

	function confirmAction(title, text, okLabel) {
		var dialog = $('confirmDialog');
		setText($('confirmTitle'), title);
		setText($('confirmText'), text);
		setText($('confirmOk'), okLabel || 'Conferma');
		dialog.returnValue = '';
		dialog.showModal();
		return new Promise(function (resolve) {
			dialog.addEventListener('close', function onClose() {
				dialog.removeEventListener('close', onClose);
				resolve(dialog.returnValue === 'ok');
			});
		});
	}

	function notifyFor(label, type) {
		var list = (state.cur && state.cur.notify_data) || [];
		for (var i = 0; i < list.length; i++) {
			if (list[i].label === label && list[i].type === (type || 'probe')) { return list[i]; }
		}
		return null;
	}

	function probeTemp(group, label) {
		var c = state.cur && state.cur.current;
		if (!c || !c[group]) { return null; }
		var v = c[group][label];
		return (typeof v === 'number' && v > 0) ? v : null;
	}

	/* ------------------------------------------------------------ targets */

	function serverTarget() {
		var s = state.cur && state.cur.current;
		return s && s.PSP > 0 ? s.PSP : null;
	}

	function shownTarget() {
		if (state.pendingTarget !== null) { return state.pendingTarget; }
		if (state.localTarget !== null && Date.now() < state.localTargetUntil) { return state.localTarget; }
		state.localTarget = null;
		var t = serverTarget();
		if (t !== null) { state.lastHoldTarget = t; return t; }
		if (state.lastHoldTarget !== null) { return state.lastHoldTarget; }
		if (CFG.after_startup_mode === 'Hold' && CFG.after_startup_setpoint) { return clampTarget(CFG.after_startup_setpoint); }
		return DEFAULT_PRESETS[1][1];
	}

	function presets() {
		if (!CFG.presets) { return DEFAULT_PRESETS; }
		var list = String(CFG.presets).split(',').map(function (item) {
			var parts = item.split(':');
			var value = parseFloat(parts[parts.length - 1]);
			var label = parts.length > 1 ? parts.slice(0, -1).join(':').trim() : String(value) + '°';
			return [label, value];
		}).filter(function (p) { return !isNaN(p[1]); });
		return list.length ? list.slice(0, 6) : DEFAULT_PRESETS;
	}

	function sendHold(target) {
		var mode = state.cur ? state.cur.status.mode : '';
		if (['Smoke', 'Hold'].indexOf(mode) < 0) { return Promise.resolve(); }
		state.localTarget = target;
		state.localTargetUntil = Date.now() + LOCAL_WINS_MS;
		state.lastHoldTarget = target;
		var path = mode === 'Hold' ? 'psp/' + target : 'mode/hold/' + target;
		return api(path).then(function () {
			toast('Target ' + target + '°' + UNITS);
		}).catch(function () { state.localTarget = null; });
	}

	function nudgeTarget(delta) {
		var base = shownTarget();
		var next = clampTarget(Math.round(base / LIMITS.step) * LIMITS.step + delta);
		state.pendingTarget = next;
		renderControl();
		clearTimeout(state.holdTimer);
		state.holdTimer = setTimeout(function () {
			var t = state.pendingTarget;
			state.pendingTarget = null;
			if (t !== null) { sendHold(t); }
		}, HOLD_DEBOUNCE_MS);
	}

	/* ------------------------------------------------------------ rendering */

	function render() {
		if (!state.cur) { return; }
		renderStrip();
		renderGrill();
		renderControl();
		renderProbes();
		renderStatus();
	}

	function renderStrip() {
		var chip = $('chipOnline');
		var online = state.errors < OFFLINE_AFTER;
		chip.classList.toggle('is-online', online);
		chip.classList.toggle('is-offline', !online);
		setText(chip.querySelector('.md-chip-text'), online ? 'Online' : 'Non raggiungibile');
		show($('chipMqtt'), CFG.mqtt);
		show($('bannerOffline'), !online);
		var st = state.cur.status;
		show($('bannerError'), !!st.critical_error);
		var lid = !!st.lid_open_detected;
		show($('chipLid'), lid);
		if (lid && st.lid_open_endtime) {
			setText($('lidRemaining'), fmtDuration(st.lid_open_endtime - now(), true));
		} else {
			setText($('lidRemaining'), '');
		}
	}

	function phaseInfo(st) {
		// Startup / Reignite / Shutdown / Prime run for a known duration from start_time
		var duration = 0, title = '', note = '';
		if (st.mode === 'Startup' || st.mode === 'Reignite') {
			duration = st.start_duration;
			title = st.mode === 'Startup' ? 'Accensione in corso' : 'Riaccensione in corso';
			var after = CFG.after_startup_mode === 'Hold'
				? 'poi Mantenimento a ' + fmtTemp(CFG.after_startup_setpoint) + '°'
				: 'poi ' + (MODE_IT[CFG.after_startup_mode] || CFG.after_startup_mode);
			note = 'Candeletta accesa, ' + after + '.';
		} else if (st.mode === 'Shutdown') {
			duration = st.shutdown_duration;
			title = 'Spegnimento in corso';
			note = 'La ventola brucia il pellet rimasto nel braciere.';
		} else if (st.mode === 'Prime') {
			duration = st.prime_duration;
			title = 'Caricamento pellet';
			note = (st.prime_amount ? st.prime_amount + ' g' : '') ;
		}
		var elapsed = st.start_time ? now() - st.start_time : 0;
		var remaining = duration ? Math.max(0, duration - elapsed) : 0;
		return { title: title, note: note, duration: duration, elapsed: elapsed, remaining: remaining,
			pct: duration ? Math.min(100, elapsed / duration * 100) : 0 };
	}

	function renderGrill() {
		var st = state.cur.status;
		var mode = st.mode;
		var burning = FIRE_MODES.indexOf(mode) >= 0;
		var dot = $('modeDot');
		dot.style.background = mode === 'Error' ? 'var(--em-danger)'
			: (burning || mode === 'Shutdown') ? 'var(--em-ember)'
			: mode === 'Monitor' ? 'var(--em-probe1)' : 'var(--em-muted)';
		setText($('modeLabel'), MODE_IT[mode] || mode);

		var grill = probeTemp('P', primary);
		setText($('grillTemp'), fmtTemp(grill));
		document.querySelector('.md-grill').classList.toggle('is-idle', !burning && mode !== 'Shutdown');

		// "In cottura da": time since the grill was started
		var cooking = (burning || mode === 'Shutdown') && st.startup_timestamp > 0;
		show($('elapsedWrap'), cooking);
		if (cooking) {
			setText($('elapsedLabel'), mode === 'Shutdown' ? 'Cottura durata' : 'In cottura da');
			setText($('elapsed'), fmtDuration(now() - st.startup_timestamp));
		}

		var target = mode === 'Hold' ? shownTarget() : null;
		show($('pillTarget'), target !== null);
		if (target !== null) { setText($('pillTargetVal'), fmtTemp(target) + '°'); }

		var phase = phaseInfo(st);
		var showPhase = !!phase.duration && ['Startup', 'Reignite', 'Shutdown', 'Prime'].indexOf(mode) >= 0;
		show($('pillPhase'), showPhase);
		if (showPhase) {
			setText($('pillPhaseText'), phase.remaining > 0 ? 'Mancano' : 'Quasi finito');
			setText($('pillPhaseVal'), phase.remaining > 0 ? fmtDuration(phase.remaining, true) : '');
		}
		show($('pillSplus'), !!splusOn() && (mode === 'Smoke' || mode === 'Hold'));

		// progress: towards the target in Hold, through the phase in Startup/Shutdown; hidden otherwise
		var pct = null;
		if (target && grill) { pct = Math.min(100, grill / target * 100); }
		else if (showPhase) { pct = phase.pct; }
		show($('grillBar').parentNode, pct !== null);
		if (pct !== null) { $('grillBar').style.width = pct.toFixed(1) + '%'; }
	}

	function splusOn() {
		if (state.localSplus !== null && Date.now() < state.localSplusUntil) { return state.localSplus; }
		state.localSplus = null;
		return !!state.cur.status.s_plus;
	}

	function panelFor(mode) {
		if (mode === 'Smoke' || mode === 'Hold') { return 'run'; }
		if (mode === 'Recipe') { return 'recipe'; }
		if (['Startup', 'Reignite', 'Shutdown', 'Prime'].indexOf(mode) >= 0) { return 'phase'; }
		if (['Stop', 'Monitor', 'Error'].indexOf(mode) >= 0) { return 'idle'; }
		return 'other';
	}

	function renderControl() {
		if (!state.cur) { return; }
		var st = state.cur.status;
		var mode = st.mode;
		var panel = panelFor(mode);
		document.querySelectorAll('.md-panel').forEach(function (el) { show(el, el.dataset.panel === panel); });

		if (panel === 'run') {
			document.querySelectorAll('.md-seg button').forEach(function (b) {
				b.setAttribute('aria-pressed', String(b.dataset.mode === mode.toLowerCase()));
			});
			var target = shownTarget();
			setText($('targetValue'), fmtTemp(target) + '°');
			$('targetValue').parentNode.classList.toggle('is-pending', state.pendingTarget !== null);
			$('targetValue').parentNode.classList.toggle('is-preview', mode !== 'Hold' && state.pendingTarget === null);
			setText($('targetHint'), mode === 'Hold' ? 'temperatura target'
				: 'tocca + o − per passare a Mantenimento');
			$('stepDown').disabled = target <= LIMITS.min;
			$('stepUp').disabled = target >= LIMITS.max;
			document.querySelectorAll('#presets button').forEach(function (b) {
				b.classList.toggle('is-active', mode === 'Hold' && Number(b.dataset.value) === Math.round(target));
			});
			var on = splusOn();
			$('splusSwitch').setAttribute('aria-pressed', String(on));
		} else if (panel === 'phase') {
			var phase = phaseInfo(st);
			setText($('phaseTitle'), phase.title);
			setText($('phaseCountdown'), phase.duration ? fmtDuration(phase.remaining, true) : '—');
			$('phaseBar').style.width = phase.pct.toFixed(1) + '%';
			setText($('phaseNote'), phase.note);
			show($('phaseShutdown'), mode !== 'Shutdown');
			show($('phaseStop'), mode === 'Shutdown' || mode === 'Prime');
		} else if (panel === 'idle') {
			var text = mode === 'Monitor' ? 'Monitoraggio attivo: le sonde vengono lette, il grill non scalda.'
				: mode === 'Error' ? 'Il controllo si è fermato per un errore. Controlla il registro eventi prima di riaccendere.'
				: 'Il grill è spento.';
			setText($('idleText'), text);
			show($('idleMonitor'), mode !== 'Monitor');
			show($('idleStop'), mode === 'Monitor');
			var after = CFG.after_startup_mode === 'Hold'
				? 'Dopo l’accensione: Mantenimento a ' + fmtTemp(CFG.after_startup_setpoint) + '°'
				: 'Dopo l’accensione: ' + (MODE_IT[CFG.after_startup_mode] || CFG.after_startup_mode);
			setText($('idleAfter'), after);
		} else if (panel === 'recipe') {
			renderRecipe(st);
		} else {
			setText($('otherText'), 'Modalità ' + (MODE_IT[mode] || mode) + ' in corso: si controlla dalla dashboard classica.');
		}
	}

	function probeName(label) {
		for (var i = 0; i < probes.length; i++) {
			if (probes[i].label === label) { return probes[i].name || label; }
		}
		return label;
	}

	function recipeStepLabel(r) {
		if (r.mode === 'Hold') { return 'Mantenimento a ' + fmtTemp(r.hold_temp) + '°'; }
		return MODE_IT[r.mode] || r.mode || '—';
	}

	function renderRecipe(st) {
		var r = state.data && state.data.recipe;
		var waiting = !!st.recipe_paused || !!(r && r.waiting);
		setText($('recipeTitle'), r && r.title ? 'Ricetta · ' + r.title : 'Ricetta');
		if (!r) {
			setText($('recipeStep'), 'Ricetta in corso');
			setText($('recipeEnd'), '');
		} else {
			setText($('recipeStep'), (r.steps ? 'Fase ' + r.step + ' di ' + r.steps + ' · ' : '') + recipeStepLabel(r));
			var ends = [];
			var timer = state.data.timer;
			if (r.timer > 0) {
				if (timer && timer.state === 'running') {
					var left = timer.end ? timer.end - (Date.now() / 1000 + state.serverOffset) : timer.remaining;
					ends.push('tra ' + fmtDuration(left, left < 3600));
				} else {
					ends.push('dopo ' + fmtDuration(r.timer * 60));
				}
			}
			Object.keys(r.targets || {}).forEach(function (label) {
				ends.push(label === primary
					? 'quando il grill arriva a ' + fmtTemp(r.targets[label]) + '°'
					: 'quando ' + probeName(label) + ' arriva a ' + fmtTemp(r.targets[label]) + '°');
			});
			var end;
			if (waiting) { end = 'Il grill tiene la temperatura e aspetta te.'; }
			else if (r.mode === 'Startup') { end = 'La fase finisce con l’accensione.'; }
			else if (r.mode === 'Shutdown') { end = 'Ultima fase: poi il grill si ferma.'; }
			else if (ends.length) { end = 'Finisce ' + ends.join(' oppure '); }
			else { end = ''; }
			if (!waiting && r.next_mode) { end += (end ? ' · ' : '') + 'Poi: ' + recipeStepLabel({mode: r.next_mode, hold_temp: r.next_hold}); }
			setText($('recipeEnd'), end);
		}
		var msg = r && r.message;
		show($('recipeMsg'), waiting && !!msg);
		setText($('recipeMsg'), waiting && msg ? msg : '');
		show($('recipeContinue'), waiting);
		show($('recipeNext'), !waiting);
	}

	function renderProbes() {
		document.querySelectorAll('.md-probe').forEach(function (card) {
			var label = card.dataset.probe;
			var temp = probeTemp('F', label);
			var n = notifyFor(label, 'probe');
			var active = !!(n && n.req);
			// PiFire clears target/req once the target is reached; 'achieved' keeps the value (fork)
			var achieved = n && n.achieved > 0 ? n.achieved : null;
			var target = active && n.target > 0 ? n.target : achieved;
			var ready = target !== null && temp !== null &&
				(active ? temp >= target : temp >= target - READY_MARGIN);
			var showTarget = target !== null && (active || ready);

			card.classList.toggle('is-ready', ready && showTarget);
			card.classList.toggle('is-disconnected', temp === null);
			setText(card.querySelector('.md-probe-temp'), temp === null ? '—' : fmtTemp(temp) + '°');
			setText(card.querySelector('.md-probe-target'), showTarget ? '→ ' + fmtTemp(target) + '°' : '');

			var status;
			if (temp === null) { status = 'Non collegata'; }
			else if (ready && showTarget) { status = 'PRONTO'; }
			else if (showTarget && n.eta) { status = 'pronta tra ~' + fmtDuration(n.eta); }
			else if (showTarget) { status = 'target attivo'; }
			else { status = 'Imposta target'; }
			setText(card.querySelector('.md-probe-status'), status);

			var pct = showTarget && temp !== null ? Math.min(100, temp / target * 100) : 0;
			card.querySelector('.md-probe-bar').style.width = pct.toFixed(1) + '%';
		});
	}

	function renderStatus() {
		var out = state.cur.status.outpins || {};
		var set = function (id, on, onText, offText) {
			var el = $(id);
			el.classList.toggle('is-on', !!on);
			setText(el, on ? onText : offText);
		};
		set('statFan', out.fan, 'Accesa', 'Spenta');
		set('statAuger', out.auger, 'In carico', 'Ferma');
		set('statIgniter', out.igniter, 'Accesa', 'Spenta');

		var d = state.data;
		if (CFG.hopper && d && d.hopper_level !== null && d.hopper_level !== undefined) {
			setText($('statPelletLabel'), 'Livello pellet');
			setText($('statPellet'), d.hopper_level + '%');
		} else if (d && d.pellets_g !== null && d.pellets_g !== undefined) {
			setText($('statPelletLabel'), 'Pellet usato (stima)');
			setText($('statPellet'), d.pellets_g >= 1000
				? (d.pellets_g / 1000).toFixed(1).replace('.', ',') + ' kg'
				: d.pellets_g + ' g');
		} else {
			setText($('statPellet'), '—');
		}
	}

	/* ------------------------------------------------------------ timer */

	function renderTimer() {
		var t = state.data && state.data.timer;
		var card = $('timerCard');
		var st = t ? t.state : 'idle';
		// PiFire resets the timer as soon as it expires: keep showing "scaduto" for a while
		if (st === 'idle' && state.timerDoneAt && now() - state.timerDoneAt < 1800) { st = 'done'; }
		var remaining = 0;
		if (st === 'running') {
			remaining = Math.max(0, t.end - now());
			if (remaining <= 0) { st = 'done'; }
		} else if (st === 'paused') {
			remaining = t.remaining;
		}
		card.classList.toggle('is-done', st === 'done');
		show($('timerQuick'), st === 'idle' || st === 'done');
		show($('timerPause'), st === 'running');
		show($('timerResume'), st === 'paused');
		show($('timerStop'), st !== 'idle');
		setText($('timerStop'), st === 'done' ? 'Chiudi' : 'Annulla');

		if (st === 'idle') {
			setText($('timerValue'), '—');
			setText($('timerNote'), 'Nessun timer attivo');
		} else if (st === 'done') {
			setText($('timerValue'), '0:00');
			setText($('timerNote'), 'Tempo scaduto');
		} else {
			setText($('timerValue'), fmtDuration(remaining, true));
			var extra = [];
			if (st === 'paused') { extra.push('In pausa'); } else { extra.push('Fine alle ' + clockTime(t.end)); }
			if (t.shutdown) { extra.push(t.keep_warm ? 'poi tiene in caldo' : 'poi spegne il grill'); }
			setText($('timerNote'), extra.join(' · '));
		}
	}

	function startTimer(seconds, shutdown, keepWarm) {
		var chain = api('timer/stop').catch(function () {});
		chain.then(function () { return api('timer/start/' + seconds); })
			.then(function () { return api('timer/shutdown/' + (shutdown ? 'true' : 'false')); })
			.then(function () { return api('timer/keep_warm/' + (keepWarm ? 'true' : 'false')); })
			.then(function () { toast('Timer avviato: ' + fmtDuration(seconds)); loadData(); setTimeout(loadData, 1500); })
			.catch(function () {});
	}

	/* ------------------------------------------------------------ chart */

	var SERIES_COLORS = {};
	probes.forEach(function (p) { SERIES_COLORS[p.group + ':' + p.label] = p.color; });

	function niceStep(range) {
		var steps = [10, 20, 25, 50, 100, 200];
		for (var i = 0; i < steps.length; i++) { if (range / steps[i] <= 4) { return steps[i]; } }
		return 250;
	}

	function renderChart() {
		var d = state.data;
		var plot = $('chartPlot');
		var svg = $('chartSvg');
		var W = Math.max(100, plot.clientWidth), H = plot.clientHeight || 240;
		var minutes = state.minutes;
		setText($('chartTitle'), minutes >= 120 ? 'Ultime ' + (minutes / 60) + ' ore' : 'Ultimi ' + minutes + ' minuti');
		document.querySelectorAll('.md-range button').forEach(function (b) {
			b.setAttribute('aria-pressed', String(Number(b.dataset.minutes) === minutes));
		});

		var chart = d && d.chart;
		var tEnd = (d ? d.server_time : now()) * 1000;
		var tStart = tEnd - minutes * 60000;
		var series = [];
		if (chart && chart.T.length) {
			probes.forEach(function (p) {
				var values = (chart[p.group] || {})[p.label];
				if (!values || p.hidden) { return; }
				if (!values.some(function (v) { return v !== null; })) { return; }
				series.push({ key: p.group + ':' + p.label, name: p.name, color: p.color, values: values, width: p.group === 'P' ? 2.8 : 2.2 });
			});
		}
		var hasSetpoint = chart && chart.PSP.some(function (v) { return v !== null; });
		show($('chartEmpty'), !series.length);

		// y range: 0 .. a round number above everything that is drawn
		var vmax = 0;
		series.forEach(function (s) { s.values.forEach(function (v) { if (v !== null && v > vmax) { vmax = v; } }); });
		if (hasSetpoint) { chart.PSP.forEach(function (v) { if (v !== null && v > vmax) { vmax = v; } }); }
		var headroom = vmax ? 1.08 : 1;
		if (!vmax) { vmax = UNITS === 'C' ? 150 : 300; }
		var step = niceStep(vmax * headroom);
		var ymax = Math.ceil(vmax * headroom / step) * step;
		var y = function (v) { return H - (v / ymax) * H; };
		var x = function (t) { return (t - tStart) / (tEnd - tStart) * W; };

		var parts = [];
		var ticks = [];
		for (var v = 0; v <= ymax + 0.01; v += step) { ticks.push(v); }
		ticks.forEach(function (tv) {
			parts.push('<line x1="0" x2="' + W + '" y1="' + y(tv).toFixed(1) + '" y2="' + y(tv).toFixed(1) + '" stroke="' + (tv === 0 ? '#2C3033' : '#24282B') + '" stroke-width="1"/>');
		});

		var pathFor = function (values) {
			var dpath = '', pen = false;
			for (var i = 0; i < values.length; i++) {
				var val = values[i], t = chart.T[i];
				if (val === null || t < tStart) { pen = false; continue; }
				// break the line across gaps longer than 2 minutes (grill off, control restarted)
				if (pen && t - chart.T[i - 1] > 120000) { pen = false; }
				dpath += (pen ? 'L' : 'M') + x(t).toFixed(1) + ',' + y(val).toFixed(1);
				pen = true;
			}
			return dpath;
		};
		if (hasSetpoint) {
			parts.push('<path d="' + pathFor(chart.PSP) + '" fill="none" stroke="#A85A2A" stroke-width="1.5" stroke-dasharray="6 6"/>');
		}
		// food probes first, grill on top
		series.slice().reverse().forEach(function (s) {
			parts.push('<path d="' + pathFor(s.values) + '" fill="none" stroke="' + s.color + '" stroke-width="' + s.width + '" stroke-linejoin="round" stroke-linecap="round"/>');
		});
		svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
		svg.innerHTML = parts.join('');

		// y labels
		$('chartY').innerHTML = ticks.map(function (tv) {
			return '<span style="top:' + (y(tv) / H * 100).toFixed(2) + '%">' + tv + '°</span>';
		}).join('');
		// x labels: -minutes .. now in 3 steps
		var xl = [];
		for (var k = 3; k >= 0; k--) {
			var m = minutes * k / 3;
			var label = k === 0 ? 'ora' : (minutes >= 180 ? '−' + (m / 60) + ' h' : '−' + Math.round(m) + '′');
			xl.push('<span style="left:' + ((3 - k) / 3 * 100).toFixed(2) + '%">' + label + '</span>');
		}
		$('chartX').innerHTML = xl.join('');

		// legend
		var legend = series.map(function (s) {
			return '<span><i style="background:' + s.color + '"></i>' + escapeHtml(s.name) + '</span>';
		});
		if (hasSetpoint) { legend.push('<span class="is-muted"><i class="is-dashed"></i>Target</span>'); }
		$('chartLegend').innerHTML = legend.join('');

		// live dot on the grill line
		var dot = $('chartDot');
		var grillSeries = series.filter(function (s) { return s.key === 'P:' + primary; })[0];
		var lastVal = null, lastT = null;
		if (grillSeries) {
			for (var j = grillSeries.values.length - 1; j >= 0; j--) {
				if (grillSeries.values[j] !== null) { lastVal = grillSeries.values[j]; lastT = chart.T[j]; break; }
			}
		}
		show(dot, lastVal !== null && tEnd - lastT < 120000);
		if (lastVal !== null) {
			dot.style.left = (x(lastT) / W * 100).toFixed(2) + '%';
			dot.style.top = (y(lastVal) / H * 100).toFixed(2) + '%';
		}
		svg.setAttribute('aria-label', 'Grafico temperature, ' + $('chartTitle').textContent.toLowerCase());
	}

	function escapeHtml(s) {
		return String(s).replace(/[&<>"']/g, function (c) {
			return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
		});
	}

	/* ------------------------------------------------------------ polling */

	function fetchJson(url, timeoutMs) {
		var ctrl = window.AbortController ? new AbortController() : null;
		var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, timeoutMs || 5000) : null;
		return fetch(url, { cache: 'no-store', signal: ctrl ? ctrl.signal : undefined })
			.then(function (r) { if (!r.ok) { throw new Error(r.status); } return r.json(); })
			.finally(function () { if (timer) { clearTimeout(timer); } });
	}

	function anyDialogOpen() {
		return !!document.querySelector('dialog[open]');
	}

	function loadCurrent() {
		return fetchJson('/api/current', 4000).then(function (cur) {
			state.errors = 0;
			if (state.uiHash === null) { state.uiHash = cur.status.ui_hash; }
			else if (cur.status.ui_hash !== state.uiHash && !anyDialogOpen()) {
				// probes or settings changed on the server: the page layout is stale
				location.reload();
				return;
			}
			var prevMode = state.cur ? state.cur.status.mode : null;
			var prevPaused = state.cur ? !!state.cur.status.recipe_paused : false;
			state.cur = cur;
			render();
			if ((prevMode && prevMode !== cur.status.mode) || prevPaused !== !!cur.status.recipe_paused) { loadData(); }
			else if (cur.status.mode === 'Recipe' && Date.now() - state.dataAt > 5000) { loadData(); }
		}).catch(function () {
			state.errors += 1;
			if (state.cur) { renderStrip(); }
		});
	}

	function loadData() {
		return fetchJson('/dash/modern/data?minutes=' + state.minutes, 8000).then(function (d) {
			state.serverOffset = d.server_time - Date.now() / 1000;
			var before = state.data && state.data.timer;
			if (before && before.state === 'running' && d.timer.state === 'idle' && before.end <= d.server_time + 20) {
				state.timerDoneAt = before.end;
			}
			if (d.timer.state !== 'idle') { state.timerDoneAt = 0; }
			state.data = d;
			state.dataAt = Date.now();
			if (typeof d.mqtt === 'boolean') { CFG.mqtt = d.mqtt; }
			renderChart();
			renderTimer();
			if (state.cur) { renderStatus(); renderControl(); }
		}).catch(function () {});
	}

	/* ------------------------------------------------------------ events */

	function buildPresets() {
		$('presets').innerHTML = presets().map(function (p) {
			return '<button type="button" data-value="' + p[1] + '"><span>' + escapeHtml(p[0]) + '</span><span class="md-num">' + fmtTemp(p[1]) + '°</span></button>';
		}).join('');
		$('foodPresets').innerHTML = FOOD_PRESETS.map(function (p) {
			return '<button type="button" data-value="' + p[1] + '"><span>' + escapeHtml(p[0]) + '</span><span class="md-num">' + p[1] + '°</span></button>';
		}).join('');
	}

	function doShutdown() {
		confirmAction('Avviare lo spegnimento?',
			'La coclea si ferma e la ventola resta accesa per bruciare il pellet rimasto, poi il grill si spegne.',
			'Spegni').then(function (ok) { if (ok) { api('mode/shutdown').then(loadCurrent).catch(function () {}); } });
	}

	function bind() {
		$('stepDown').addEventListener('click', function () { nudgeTarget(-LIMITS.step); });
		$('stepUp').addEventListener('click', function () { nudgeTarget(LIMITS.step); });

		$('presets').addEventListener('click', function (e) {
			var b = e.target.closest('button');
			if (!b) { return; }
			clearTimeout(state.holdTimer);
			state.pendingTarget = null;
			sendHold(Number(b.dataset.value)).then(render);
			render();
		});

		document.querySelector('.md-seg').addEventListener('click', function (e) {
			var b = e.target.closest('button');
			if (!b || !state.cur) { return; }
			var mode = state.cur.status.mode;
			if (b.dataset.mode === 'shutdown') { doShutdown(); return; }
			if (b.dataset.mode === 'smoke' && mode !== 'Smoke') {
				api('mode/smoke').then(loadCurrent).catch(function () {});
			} else if (b.dataset.mode === 'hold' && mode !== 'Hold') {
				clearTimeout(state.holdTimer);
				state.pendingTarget = null;
				sendHold(shownTarget()).then(loadCurrent);
			}
		});

		$('splusSwitch').addEventListener('click', function () {
			if (!state.cur) { return; }
			var next = !splusOn();
			state.localSplus = next;
			state.localSplusUntil = Date.now() + LOCAL_WINS_MS;
			render();
			api('splus/' + (next ? 'true' : 'false')).catch(function () { state.localSplus = null; render(); });
		});

		document.addEventListener('click', function (e) {
			var b = e.target.closest('[data-action]');
			if (!b) { return; }
			var action = b.dataset.action;
			if (action === 'shutdown') { doShutdown(); }
			else if (action === 'stop') {
				var burning = state.cur && FIRE_MODES.indexOf(state.cur.status.mode) >= 0;
				confirmAction('Fermare tutto?',
					burning ? 'Il fuoco è ancora acceso: di solito è meglio lo spegnimento, che brucia il pellet rimasto.'
						: 'Ventola, coclea e candeletta si spengono subito.',
					'Stop').then(function (ok) { if (ok) { api('mode/stop').then(loadCurrent).catch(function () {}); } });
			} else if (action === 'startup') {
				confirmAction('Accendere il grill?',
					'Parte la candeletta e la coclea carica il pellet. Controlla che il braciere sia pulito e il coperchio chiuso.',
					'Accendi').then(function (ok) { if (ok) { api('mode/startup').then(loadCurrent).catch(function () {}); } });
			} else if (action === 'monitor') {
				api('mode/monitor').then(loadCurrent).catch(function () {});
			} else if (action === 'recipe-continue') {
				api('recipe/continue').then(function () { toast('Si riparte'); loadCurrent(); loadData(); }).catch(function () {});
			} else if (action === 'recipe-next') {
				confirmAction('Passare alla fase successiva?',
					'La fase in corso finisce subito e il programma della ricetta va avanti.',
					'Avanti').then(function (ok) { if (ok) { api('recipe/next').then(function () { loadCurrent(); loadData(); }).catch(function () {}); } });
			}
		});

		document.querySelector('.md-range').addEventListener('click', function (e) {
			var b = e.target.closest('button');
			if (!b) { return; }
			state.minutes = Number(b.dataset.minutes);
			renderChart();
			loadData();
		});

		// Probe target dialog
		var probeDialog = $('probeDialog');
		var probeInput = $('probeTarget');
		document.querySelectorAll('.md-probe').forEach(function (card) {
			card.addEventListener('click', function () {
				var label = card.dataset.probe;
				var p = foodProbes.filter(function (fp) { return fp.label === label; })[0];
				var n = notifyFor(label, 'probe');
				state.probeDialogLabel = label;
				setText($('probeDialogName'), p ? p.name : label);
				var known = n && (n.req && n.target > 0 ? n.target : n.achieved);
				probeInput.value = known ? Math.round(known) : FOOD_PRESETS[2][1];
				show($('probeClear'), !!(n && (n.req || n.achieved)));
				probeDialog.returnValue = '';
				probeDialog.showModal();
			});
		});
		$('probeDown').addEventListener('click', function () { probeInput.value = Math.max(0, (Number(probeInput.value) || 0) - 1); });
		$('probeUp').addEventListener('click', function () { probeInput.value = (Number(probeInput.value) || 0) + 1; });
		$('foodPresets').addEventListener('click', function (e) {
			var b = e.target.closest('button');
			if (b) { probeInput.value = b.dataset.value; }
		});
		probeDialog.addEventListener('close', function () {
			var label = state.probeDialogLabel;
			if (!label) { return; }
			if (probeDialog.returnValue === 'ok') {
				var value = Number(probeInput.value);
				var maxFood = UNITS === 'C' ? 150 : 300;
				if (!(value > 0 && value <= maxFood)) { toast('Target non valido', true); return; }
				api('notify/' + label + '/target/' + value)
					.then(function () { return api('notify/' + label + '/req/true'); })
					.then(function () { toast('Target impostato: ' + value + '°' + UNITS); loadCurrent(); })
					.catch(function () {});
			} else if (probeDialog.returnValue === 'clear') {
				api('notify/' + label + '/req/false').then(function () { toast('Target rimosso'); loadCurrent(); }).catch(function () {});
			}
		});

		// Timer
		$('timerQuick').addEventListener('click', function (e) {
			var b = e.target.closest('button');
			if (!b) { return; }
			if (b.id === 'timerCustom') {
				$('timerDialog').returnValue = '';
				$('timerDialog').showModal();
				return;
			}
			startTimer(Number(b.dataset.seconds), false, false);
		});
		$('timerDialog').addEventListener('close', function () {
			if ($('timerDialog').returnValue !== 'ok') { return; }
			var seconds = (Number($('timerHours').value) || 0) * 3600 + (Number($('timerMinutes').value) || 0) * 60;
			if (seconds < 60) { toast('Imposta almeno un minuto', true); return; }
			startTimer(seconds, $('timerShutdown').checked, $('timerKeepWarm').checked);
		});
		$('timerPause').addEventListener('click', function () { api('timer/pause').then(loadData).catch(function () {}); });
		$('timerResume').addEventListener('click', function () { api('timer/start/0').then(loadData).catch(function () {}); });
		$('timerStop').addEventListener('click', function () {
			state.timerDoneAt = 0;
			renderTimer();
			api('timer/stop').then(loadData).catch(function () {});
		});

		// Dashboard settings (same /dash/config form the other dashboards use)
		$('dashGear').addEventListener('click', function () {
			$('dashSettingsDialog').showModal();
			fetch('/dash/config').then(function (r) { return r.text(); }).then(function (html) {
				$('dash_config_card').innerHTML = html;
			}).catch(function () { setText($('dash_config_card'), 'Impossibile caricare le impostazioni.'); });
		});

		window.addEventListener('resize', function () {
			clearTimeout(bind._r);
			bind._r = setTimeout(renderChart, 150);
		});
		document.addEventListener('visibilitychange', function () {
			if (!document.hidden) { loadCurrent(); loadData(); }
		});
	}

	/* ------------------------------------------------------------ start */

	buildPresets();
	bind();
	renderChart();
	renderTimer();
	loadCurrent();
	loadData();
	setInterval(function () { if (!document.hidden) { loadCurrent(); } }, FAST_MS);
	setInterval(function () { if (!document.hidden) { loadData(); } }, SLOW_MS);
	// countdowns (timer, startup, lid) tick every second between polls
	setInterval(function () {
		if (document.hidden) { return; }
		renderTimer();
		if (state.cur) { renderGrill(); renderStrip(); if (['phase', 'recipe'].indexOf(panelFor(state.cur.status.mode)) >= 0) { renderControl(); } }
	}, 1000);
})();
