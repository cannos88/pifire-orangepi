'''
Emergency access point logic.

States:
  client    connected to a saved network
  waiting   not connected; NetworkManager keeps trying the saved networks
  ap        emergency network PiFire-Setup is on (open, address 10.42.0.1)
  trying    AP switched off for a while so NetworkManager can retry the saved
            networks (the router may simply have been rebooted)

The Wi-Fi chip cannot be a client and an access point at the same time, so
the AP goes down whenever the service tries a network.  It never goes down
while a phone is using the setup page.
'''

import logging
import socket

from . import AP_SSID, AP_URL

log = logging.getLogger('wifi')

GRACE_S = 180          # disconnected this long -> emergency network
RETRY_EVERY_S = 300    # with the AP on, retry the saved networks this often...
CLIENT_QUIET_S = 180   # ...but only if nobody used the setup page for this long
TRY_WINDOW_S = 60      # how long a retry lasts before the AP comes back
SAVED_REFRESH_S = 60


class WifiManager:
	def __init__(self, nm, store, clock, grace=GRACE_S, retry_every=RETRY_EVERY_S,
				 client_quiet=CLIENT_QUIET_S, try_window=TRY_WINDOW_S, hostname=None):
		self.nm, self.store, self.clock = nm, store, clock
		self.grace, self.retry_every, self.client_quiet, self.try_window = grace, retry_every, client_quiet, try_window
		self.hostname = hostname or socket.gethostname()
		self.state = 'starting'
		self.since = clock()
		self.networks = []
		self.saved = []
		self.saved_at = -1e9
		self.scan_at = -1e9
		self.last_result = None   # {'id', 'ok', 'message'} of the last web request
		self.last_status = {}

	# ---------------------------------------------------------------- helpers

	def _set(self, state, now):
		if state != self.state:
			log.info(f'Wi-Fi: {self.state} -> {state}')
			self.state = state
			self.since = now

	def _start_ap(self, now):
		found = self.nm.scan(rescan=True)  # last chance to see networks before the radio turns AP
		if found:
			self.networks = found
		if self.nm.start_ap():
			log.warning(f'No Wi-Fi network: emergency network "{AP_SSID}" is on ({AP_URL})')
			self._set('ap', now)
		else:
			self._set('waiting', now)  # try again after another grace period

	def _result(self, request, ok, message):
		self.last_result = {'id': request.get('id'), 'action': request.get('action'), 'ok': ok, 'message': message}

	# ---------------------------------------------------------------- requests from the web app

	def handle(self, request, status, now):
		action = request.get('action')
		ssid = (request.get('ssid') or '').strip()
		password = request.get('password') or ''

		if action == 'scan':
			found = self.nm.scan(rescan=True)
			if found:
				self.networks = found
			self._result(request, True, '')
		elif action == 'add':
			ok, err = self.nm.add_network(ssid, password, activate=False)
			self._result(request, ok, f'Rete "{ssid}" salvata: il grill la userà quando è disponibile.' if ok
						 else f'Non riesco a salvare "{ssid}": {err}')
			self.saved_at = -1e9
		elif action == 'connect':
			was_ap = status.get('ap')
			if was_ap:
				self.nm.stop_ap()
			log.info(f'Wi-Fi: connecting to "{ssid}" on request')
			ok, err = self.nm.add_network(ssid, password, activate=True)
			if ok:
				self._result(request, True, f'Collegato a "{ssid}".')
				self._set('client', now)
			else:
				log.warning(f'Wi-Fi: cannot connect to "{ssid}": {err}')
				self.nm.forget('pifire-' + ssid)
				self._result(request, False, f'Non riesco a collegarmi a "{ssid}". Controlla la password e che la rete sia raggiungibile.')
				if was_ap or not status.get('connected'):
					self._start_ap(now)
			self.saved_at = -1e9
		elif action == 'forget':
			name = request.get('name') or ''
			ok, err = self.nm.forget(name)
			self._result(request, ok, 'Rete rimossa.' if ok else f'Non riesco a rimuovere la rete: {err}')
			self.saved_at = -1e9
		else:
			self._result(request, False, 'Richiesta non valida.')

	# ---------------------------------------------------------------- main step

	def tick(self):
		now = self.clock()
		status = self.nm.status()

		request = self.store.pop_request()
		if request:
			self.handle(request, status, now)
			status = self.nm.status()

		if status['state'] == 'unavailable':
			self._set('unavailable', now)
		elif status['connected']:
			self._set('client', now)
		elif status['ap']:
			if self.state != 'ap':
				self._set('ap', now)
			quiet = now - self.store.client_seen() >= self.client_quiet
			if now - self.since >= self.retry_every and quiet:
				log.info('Wi-Fi: emergency network off for a while, retrying the saved networks')
				self.nm.stop_ap()
				self._set('trying', now)
		else:
			if self.state in ('starting', 'client', 'unavailable'):
				self._set('waiting', now)
			elif self.state == 'waiting' and now - self.since >= self.grace:
				self._start_ap(now)
			elif self.state == 'trying' and now - self.since >= self.try_window:
				self._start_ap(now)
			elif self.state == 'ap':  # AP dropped by itself
				self._start_ap(now)

		self.publish(now)

	def publish(self, now):
		status = self.nm.status()
		if now - self.saved_at >= SAVED_REFRESH_S:
			self.saved = self.nm.saved_networks()
			self.saved_at = now
		if status['connected'] and now - self.scan_at >= 60:
			# while connected the radio can scan freely: keep the list fresh for the page
			found = self.nm.scan(rescan=False)
			if found:
				self.networks = found
			self.scan_at = now
		self.last_status = {
			'state': self.state,
			'since': self.since,
			'ssid': self.nm.current_ssid(status['connection']) if status['connected'] else '',
			'ip': status['ip'] if status['connected'] else '',
			'hostname': self.hostname,
			'ap': {'ssid': AP_SSID, 'url': AP_URL, 'password': '', 'qr': f'WIFI:T:nopass;S:{AP_SSID};;'},
			'networks': self.networks[:20],
			'saved': self.saved,
			'last_result': self.last_result,
			'updated': now,
		}
		self.store.write_status(self.last_status)
		return self.last_status
