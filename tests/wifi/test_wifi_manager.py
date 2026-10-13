'''
Emergency Wi-Fi network: nmcli parsing and the state machine.
'''

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from wifi import AP_CONNECTION  # noqa: E402
from wifi.manager import WifiManager  # noqa: E402
from wifi.nm import NetworkManagerCLI, split_terse  # noqa: E402


# ------------------------------------------------------------------ nmcli parsing

def test_split_terse_handles_escaped_colons():
	assert split_terse(r'Casa\:5G:78:WPA2') == ['Casa:5G', '78', 'WPA2']
	assert split_terse(r'a\\b::') == ['a\\b', '', '']


def fake_run(table):
	calls = []

	def run(args, timeout=30):
		calls.append(args)
		key = ' '.join(args)
		for prefix, result in table.items():
			if key.startswith(prefix):
				return result
		return 0, '', ''
	run.calls = calls
	return run


def test_status_and_scan_parsing():
	run = fake_run({
		'-t -f DEVICE,TYPE device': (0, 'wlan0:wifi\nlo:loopback\n', ''),
		'-t -f DEVICE,TYPE,STATE,CONNECTION device': (0, 'wlan0:wifi:connected:netplan-wlan0-Casa\nlo:loopback:unmanaged:--\n', ''),
		'-g IP4.ADDRESS device show wlan0': (0, '192.168.1.50/24\n', ''),
		'-t -f SSID,SIGNAL,SECURITY device wifi list': (0, 'Casa:70:WPA2\nCasa:40:WPA2\n:30:WPA2\nOspiti:55:\nPiFire-Setup:99:\n', ''),
	})
	nm = NetworkManagerCLI(run=run)
	st = nm.status()
	assert st['connected'] and not st['ap'] and st['ip'] == '192.168.1.50'
	nets = nm.scan()
	assert nets == [{'ssid': 'Casa', 'signal': 70, 'secure': True}, {'ssid': 'Ospiti', 'signal': 55, 'secure': False}]


def test_ap_status_is_not_connected():
	run = fake_run({
		'-t -f DEVICE,TYPE device': (0, 'wlan0:wifi\n', ''),
		'-t -f DEVICE,TYPE,STATE,CONNECTION device': (0, f'wlan0:wifi:connected:{AP_CONNECTION}\n', ''),
		'-g IP4.ADDRESS': (0, '10.42.0.1/24\n', ''),
	})
	st = NetworkManagerCLI(run=run).status()
	assert st['ap'] and not st['connected']


def test_ap_connection_is_open_and_shared():
	run = fake_run({'connection show PiFire-Setup': (10, '', 'no such connection')})
	nm = NetworkManagerCLI(ifname='wlan0', run=run)
	assert nm.start_ap()
	add = [c for c in run.calls if c[:2] == ['connection', 'add']][0]
	assert '802-11-wireless.mode' in add and add[add.index('802-11-wireless.mode') + 1] == 'ap'
	assert add[add.index('ipv4.method') + 1] == 'shared'
	assert not any(a.startswith('wifi-sec') for a in add)   # no password on the emergency network


def test_add_network_with_and_without_password():
	run = fake_run({})
	nm = NetworkManagerCLI(ifname='wlan0', run=run)
	assert nm.add_network('Casa', 'segretissima', activate=True) == (True, '')
	add = [c for c in run.calls if c[:2] == ['connection', 'add']][0]
	assert add[add.index('wifi-sec.psk') + 1] == 'segretissima'
	assert ['--wait', '40', 'connection', 'up', 'id', 'pifire-Casa'] in run.calls
	run.calls.clear()
	nm.add_network('Ospiti', '', activate=False)
	add = [c for c in run.calls if c[:2] == ['connection', 'add']][0]
	assert 'wifi-sec.psk' not in add
	assert not any(c[:2] == ['--wait', '40'] for c in run.calls)


# ------------------------------------------------------------------ state machine

class FakeNM:
	def __init__(self):
		self.connected = True
		self.ap = False
		self.known = {'Casa': 'giusta'}
		self.in_range = {'Casa'}
		self.events = []

	def status(self):
		return {'device': 'wlan0', 'state': 'connected' if (self.connected or self.ap) else 'disconnected',
				'connection': AP_CONNECTION if self.ap else ('Casa' if self.connected else ''),
				'connected': self.connected and not self.ap, 'ap': self.ap, 'ip': '192.168.1.5' if self.connected else ''}

	def current_ssid(self, connection):
		return connection

	def scan(self, rescan=True):
		return [{'ssid': s, 'signal': 60, 'secure': True} for s in sorted(self.in_range)]

	def saved_networks(self):
		return [{'name': n, 'ssid': n, 'removable': True} for n in self.known]

	def start_ap(self):
		self.ap, self.connected = True, False
		self.events.append('ap_on')
		return True

	def stop_ap(self):
		self.ap = False
		self.events.append('ap_off')
		return True

	def add_network(self, ssid, password='', activate=False, wait=40):
		self.known[ssid] = password
		if activate:
			if ssid in self.in_range and password == 'giusta':
				self.connected = True
				return True, ''
			return False, 'secrets were required'
		return True, ''

	def forget(self, name):
		self.known.pop(name.replace('pifire-', ''), None)
		return True, ''

	def autoconnect(self):
		''' what NetworkManager does by itself when the AP is off '''
		if not self.ap and any(s in self.in_range for s in self.known):
			self.connected = True


class FakeStore:
	def __init__(self):
		self.status, self.requests, self.seen = None, [], 0.0

	def write_status(self, status):
		self.status = status

	def pop_request(self):
		return self.requests.pop(0) if self.requests else None

	def client_seen(self):
		return self.seen


class Clock:
	def __init__(self):
		self.t = 1000.0

	def __call__(self):
		return self.t


def make():
	nm, store, clock = FakeNM(), FakeStore(), Clock()
	return nm, store, clock, WifiManager(nm, store, clock, hostname='pifire')


def run_for(manager, clock, seconds, step=5, every=None):
	for _ in range(int(seconds / step)):
		clock.t += step
		if every:
			every()
		manager.tick()


def test_connected_stays_client():
	nm, store, clock, m = make()
	run_for(m, clock, 600)
	assert m.state == 'client' and nm.events == []
	assert store.status['ssid'] == 'Casa' and store.status['ap']['url'] == 'http://10.42.0.1'


def test_short_outage_does_not_start_the_ap():
	nm, store, clock, m = make()
	m.tick()
	nm.connected = False
	run_for(m, clock, 120)
	nm.connected = True
	run_for(m, clock, 30)
	assert m.state == 'client' and 'ap_on' not in nm.events


def test_ap_after_grace_and_back_when_router_returns():
	nm, store, clock, m = make()
	m.tick()
	nm.connected = False
	nm.in_range = set()                      # router off
	run_for(m, clock, 200)
	assert m.state == 'ap' and nm.events == ['ap_on']
	nm.in_range = {'Casa'}                   # router back
	run_for(m, clock, 320, every=nm.autoconnect)
	assert m.state == 'client' and nm.events == ['ap_on', 'ap_off']


def test_ap_stays_on_while_a_phone_uses_the_page():
	nm, store, clock, m = make()
	m.tick()
	nm.connected, nm.in_range = False, set()
	run_for(m, clock, 200)
	assert m.state == 'ap'

	def phone():
		store.seen = clock.t
	run_for(m, clock, 900, every=phone)
	assert m.state == 'ap' and nm.events == ['ap_on']


def test_password_changed_then_new_password_from_the_page():
	nm, store, clock, m = make()
	m.tick()
	nm.connected = False
	nm.known = {'Casa': 'vecchia'}           # router password changed: saved one is wrong
	run_for(m, clock, 200)
	assert m.state == 'ap'
	assert [n['ssid'] for n in store.status['networks']] == ['Casa']   # list scanned before the AP came up

	store.requests.append({'id': 'r1', 'action': 'connect', 'ssid': 'Casa', 'password': 'sbagliata'})
	run_for(m, clock, 5)
	assert m.state == 'ap' and store.status['last_result'] == {'id': 'r1', 'action': 'connect', 'ok': False,
		'message': 'Non riesco a collegarmi a "Casa". Controlla la password e che la rete sia raggiungibile.'}

	store.requests.append({'id': 'r2', 'action': 'connect', 'ssid': 'Casa', 'password': 'giusta'})
	run_for(m, clock, 5)
	assert m.state == 'client' and store.status['last_result']['ok']
	assert nm.events == ['ap_on', 'ap_off', 'ap_on', 'ap_off']   # failed try brings the AP back


def test_add_network_while_connected_does_not_switch():
	nm, store, clock, m = make()
	m.tick()
	store.requests.append({'id': 'r3', 'action': 'add', 'ssid': 'CasaNuova', 'password': 'giusta'})
	run_for(m, clock, 5)
	assert m.state == 'client' and 'CasaNuova' in nm.known and store.status['last_result']['ok']
	assert any(s['ssid'] == 'CasaNuova' for s in store.status['saved'])
