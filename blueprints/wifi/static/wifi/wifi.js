/* Wi-Fi setup page: polls /wifi/status, sends requests to /wifi/request. */
(function () {
	'use strict';

	var root = document.getElementById('wf');
	var EMERGENCY = root.dataset.emergency === 'true';
	var HOSTNAME = root.dataset.hostname;
	var $ = function (id) { return document.getElementById(id); };

	var selected = null;      // {ssid, secure, other}
	var pending = null;       // {id, action, ssid}
	var lastNetworksKey = '';
	var lastSavedKey = '';

	function text(el, value) { if (el.textContent !== value) { el.textContent = value; } }
	function show(el, visible) { el.hidden = !visible; }

	function banner(kind, message) {
		var el = $('banner');
		el.className = 'wf-banner' + (kind ? ' is-' + kind : '');
		text(el, message);
		show(el, !!message);
	}

	function bars(signal) {
		var n = signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 30 ? 2 : 1;
		var html = '<span class="wf-bars" aria-hidden="true">';
		for (var i = 1; i <= 4; i++) { html += '<i class="' + (i <= n ? 'on' : '') + '" style="height:' + (i * 4) + 'px"></i>'; }
		return html + '</span>';
	}

	function esc(s) {
		return String(s).replace(/[&<>"']/g, function (c) {
			return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
		});
	}

	/* ------------------------------------------------------------ state */

	function renderState(data) {
		var dot = $('stateDot');
		dot.className = 'wf-dot';
		if (!data.running) {
			text($('stateTitle'), 'Servizio Wi-Fi non attivo');
			text($('stateText'), 'Su questo sistema la rete non è gestita da PiFire (manca NetworkManager o il servizio pifire-wifi).');
			show($('chooseCard'), false);
			show($('savedCard'), false);
			return;
		}
		var st = data.status;
		var title = '', body = '';
		if (st.state === 'client') {
			dot.classList.add('is-ok');
			title = 'Collegato a «' + st.ssid + '»';
			body = 'Indirizzo del grill: http://' + st.ip + '  ·  http://' + HOSTNAME + '.local';
		} else if (st.state === 'ap') {
			dot.classList.add('is-ap');
			title = 'Rete di emergenza attiva';
			body = EMERGENCY
				? 'Il grill non trova una rete conosciuta. Scegli la rete di casa e scrivi la password: il grill si collega e questa rete si spegne.'
				: 'Il grill ha acceso la rete «' + st.ap.ssid + '».';
		} else if (st.state === 'trying') {
			dot.classList.add('is-wait');
			title = 'Nuovo tentativo con le reti salvate…';
			body = 'Se nessuna risponde entro un minuto torna la rete di emergenza «' + st.ap.ssid + '».';
		} else if (st.state === 'waiting' || st.state === 'starting') {
			dot.classList.add('is-wait');
			title = 'Rete non disponibile';
			body = 'Il grill riprova da solo. Se non si collega entro 3 minuti accende la rete di emergenza «' + st.ap.ssid + '», senza password.';
		} else {
			title = 'Wi-Fi non disponibile';
			body = 'NetworkManager non risponde.';
		}
		text($('stateTitle'), title);
		text($('stateText'), body);

		show($('chooseCard'), true);
		text($('chooseTitle'), EMERGENCY ? 'Scegli la rete di casa' : 'Aggiungi una rete');
		renderNetworks(st.networks || []);
		show($('savedCard'), !EMERGENCY);
		if (!EMERGENCY) { renderSaved(st.saved || []); }

		var result = st.last_result;
		if (pending && result && result.id === pending.id) {
			banner(result.ok ? 'ok' : 'error', result.message || (result.ok ? 'Fatto.' : 'Non riuscito.'));
			pending = null;
			$('connectBtn').disabled = false;
			$('saveBtn').disabled = false;
		}
	}

	function renderNetworks(networks) {
		var key = JSON.stringify(networks);
		if (key === lastNetworksKey) { return; }
		lastNetworksKey = key;
		var list = $('networks');
		if (!networks.length) {
			list.innerHTML = '<p class="wf-muted wf-small">Nessuna rete trovata. Usa «Aggiorna elenco» o scrivi il nome a mano.</p>';
			return;
		}
		list.innerHTML = networks.map(function (n) {
			var checked = selected && !selected.other && selected.ssid === n.ssid;
			return '<button type="button" class="wf-net" role="radio" aria-checked="' + checked + '" data-ssid="' + esc(n.ssid) +
				'" data-secure="' + n.secure + '">' + bars(n.signal) + '<span class="wf-net-name">' + esc(n.ssid) + '</span>' +
				(n.secure ? '<span class="wf-lock" aria-label="protetta">🔒</span>' : '<span class="wf-muted wf-small">aperta</span>') +
				'</button>';
		}).join('');
	}

	function renderSaved(saved) {
		var key = JSON.stringify(saved);
		if (key === lastSavedKey) { return; }
		lastSavedKey = key;
		$('saved').innerHTML = saved.length ? saved.map(function (s) {
			return '<div class="wf-saved"><span class="wf-net-name">' + esc(s.ssid || s.name) + '</span>' +
				(s.removable ? '<button type="button" class="wf-link" data-forget="' + esc(s.name) + '">Rimuovi</button>'
					: '<span class="wf-muted wf-small">configurata nel sistema</span>') + '</div>';
		}).join('') : '<p class="wf-muted wf-small">Nessuna rete salvata.</p>';
	}

	/* ------------------------------------------------------------ selection and form */

	function select(choice) {
		selected = choice;
		document.querySelectorAll('.wf-net').forEach(function (b) {
			var on = choice.other ? b.id === 'otherNet' : (b.dataset.ssid === choice.ssid && b.id !== 'otherNet');
			b.setAttribute('aria-checked', String(on));
		});
		show($('form'), true);
		show($('ssidField'), !!choice.other);
		var needsPassword = choice.other || choice.secure;
		show($('passwordField'), true);
		show($('openHint'), !needsPassword);
		$('password').value = '';
		$('password').required = !!choice.secure && !choice.other;
		show($('saveBtn'), !EMERGENCY);
		// on the home network the safe choice (save, keep the current network) is the main button
		$('connectBtn').classList.toggle('wf-btn-primary', EMERGENCY);
		$('saveBtn').classList.toggle('wf-btn-primary', !EMERGENCY);
		$('saveBtn').style.order = EMERGENCY ? '' : '-1';
		text($('connectBtn'), EMERGENCY ? 'Collega' : 'Collega ora');
		text($('formHint'), EMERGENCY ? ''
			: '«Salva per dopo» la tiene pronta senza cambiare rete. «Collega ora» cambia rete subito: questa pagina perde la connessione.');
		(choice.other ? $('ssid') : (needsPassword ? $('password') : $('connectBtn'))).focus();
	}

	function send(action, fields) {
		return fetch('/wifi/request', {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(Object.assign({ action: action }, fields))
		}).then(function (r) { return r.json(); });
	}

	function submit(action) {
		if (!selected) { return; }
		var ssid = selected.other ? $('ssid').value.trim() : selected.ssid;
		var password = $('password').value;
		if (!ssid) { banner('error', 'Scrivi il nome della rete.'); return; }
		if (password && (password.length < 8 || password.length > 63)) {
			banner('error', 'La password Wi-Fi deve avere da 8 a 63 caratteri.');
			return;
		}
		$('connectBtn').disabled = true;
		$('saveBtn').disabled = true;
		send(action, { ssid: ssid, password: password }).then(function (res) {
			if (!res.ok) {
				banner('error', res.message || 'Richiesta rifiutata.');
				$('connectBtn').disabled = false;
				$('saveBtn').disabled = false;
				return;
			}
			pending = { id: res.id, action: action, ssid: ssid };
			$('password').value = '';
			if (action === 'connect' && EMERGENCY) {
				banner('', 'Il grill si sta collegando a «' + ssid + '». Tra pochi secondi questa rete di emergenza si spegne: ' +
					'ricollega il telefono alla rete di casa e apri http://' + HOSTNAME + '.local (l’indirizzo compare anche sul display del grill). ' +
					'Se la password è sbagliata, la rete «PiFire-Setup» torna entro un minuto.');
			} else if (action === 'connect') {
				banner('', 'Il grill sta passando a «' + ssid + '». Se cambia rete questa pagina smette di aggiornarsi: riaprila da quella rete.');
			} else {
				banner('', 'Salvataggio di «' + ssid + '»…');
			}
		}).catch(function () {
			banner('error', 'Il grill non risponde.');
			$('connectBtn').disabled = false;
			$('saveBtn').disabled = false;
		});
	}

	/* ------------------------------------------------------------ events */

	$('networks').addEventListener('click', function (e) {
		var b = e.target.closest('.wf-net');
		if (b) { select({ ssid: b.dataset.ssid, secure: b.dataset.secure === 'true', other: false }); }
	});
	$('otherNet').addEventListener('click', function () { select({ ssid: '', secure: true, other: true }); });
	$('form').addEventListener('submit', function (e) { e.preventDefault(); submit('connect'); });
	$('saveBtn').addEventListener('click', function () { submit('add'); });
	$('showPassword').addEventListener('click', function () {
		var input = $('password');
		var visible = input.type === 'text';
		input.type = visible ? 'password' : 'text';
		text($('showPassword'), visible ? 'Mostra' : 'Nascondi');
	});
	$('rescan').addEventListener('click', function () {
		send('scan', {}).then(function () { banner('', 'Ricerca delle reti…'); setTimeout(function () { banner('', ''); }, 4000); });
	});
	$('saved').addEventListener('click', function (e) {
		var b = e.target.closest('[data-forget]');
		if (!b) { return; }
		if (!window.confirm('Rimuovere la rete «' + b.dataset.forget.replace(/^pifire-/, '') + '»?')) { return; }
		send('forget', { name: b.dataset.forget }).then(function (res) {
			if (res.ok) { pending = { id: res.id, action: 'forget' }; } else { banner('error', res.message); }
		});
	});

	text($('foot'), EMERGENCY
		? 'Sei sulla rete di emergenza del grill: da qui puoi solo configurare il Wi-Fi.'
		: 'La rete di emergenza «PiFire-Setup» (senza password) si accende da sola se il grill resta senza Wi-Fi per 3 minuti.');

	function poll() {
		fetch('/wifi/status', { cache: 'no-store' })
			.then(function (r) { return r.json(); })
			.then(renderState)
			.catch(function () {
				if (!pending) { text($('stateTitle'), 'Il grill non risponde'); }
			});
	}
	poll();
	setInterval(poll, 3000);
})();
