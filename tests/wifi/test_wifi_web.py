'''
Wi-Fi page: who may do what, and request validation.
'''

import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from blueprints.wifi.guard import allowed_on_emergency, client_ip, is_emergency_client  # noqa: E402

flask = pytest.importorskip('flask')


def test_client_ip_trusts_proxy_headers_only_from_localhost():
	assert client_ip('127.0.0.1', {'X-Real-IP': '10.42.0.23'}) == '10.42.0.23'
	assert client_ip('192.168.1.20', {'X-Real-IP': '10.42.0.23'}) == '192.168.1.20'
	assert client_ip('127.0.0.1', {'X-Forwarded-For': '10.42.0.9, 127.0.0.1'}) == '10.42.0.9'
	assert client_ip('127.0.0.1', {}) == '127.0.0.1'


def test_emergency_network_detection():
	assert is_emergency_client('10.42.0.23')
	assert not is_emergency_client('10.42.0.1')       # the grill itself
	assert not is_emergency_client('192.168.1.20')
	assert not is_emergency_client('garbage')
	assert allowed_on_emergency('/wifi/status') and allowed_on_emergency('/static/css/ember.css')
	assert not allowed_on_emergency('/api/set/mode/startup') and not allowed_on_emergency('/dash/')


class MemoryRedis:
	def __init__(self):
		self.kv, self.lists = {}, {}

	def get(self, k):
		return self.kv.get(k)

	def set(self, k, v):
		self.kv[k] = v

	def rpush(self, k, v):
		self.lists.setdefault(k, []).append(v)

	def lpop(self, k):
		return self.lists.get(k, []).pop(0) if self.lists.get(k) else None


@pytest.fixture
def app_and_store(monkeypatch):
	import time
	from flask import Flask, redirect, request
	from wifi.state import RedisStore
	import blueprints.wifi.routes as routes
	from blueprints.wifi import wifi_bp

	store = RedisStore(MemoryRedis())
	store.write_status({'state': 'ap', 'updated': time.time(), 'saved': [{'name': 'pifire-Casa', 'ssid': 'Casa', 'removable': True}],
						'networks': [], 'ap': {'ssid': 'PiFire-Setup', 'url': 'http://10.42.0.1'}, 'last_result': None})
	monkeypatch.setattr(routes, '_store', store)

	app = Flask(__name__, root_path=ROOT)
	app.register_blueprint(wifi_bp, url_prefix='/wifi')

	@app.before_request
	def guard():
		if is_emergency_client(client_ip(request.remote_addr, request.headers)) and not allowed_on_emergency(request.path):
			return redirect('/wifi/')

	@app.route('/api/set/mode/<mode>', methods=['POST'])
	def api(mode):
		return 'grill command accepted'

	return app, store


PHONE_ON_AP = {'REMOTE_ADDR': '127.0.0.1'}
AP_HEADERS = {'X-Real-IP': '10.42.0.23'}


def test_emergency_phone_cannot_reach_the_grill(app_and_store):
	app, _ = app_and_store
	c = app.test_client()
	r = c.post('/api/set/mode/startup', headers=AP_HEADERS, environ_base=PHONE_ON_AP)
	assert r.status_code == 302 and r.headers['Location'].endswith('/wifi/')
	r = c.get('/generate_204', headers=AP_HEADERS, environ_base=PHONE_ON_AP)   # Android captive check
	assert r.status_code == 302
	assert c.post('/api/set/mode/startup').data == b'grill command accepted'    # home network: normal


def test_emergency_phone_can_connect_but_not_forget(app_and_store):
	app, store = app_and_store
	c = app.test_client()
	r = c.post('/wifi/request', json={'action': 'connect', 'ssid': 'Casa', 'password': 'nuovapassword'},
			   headers=AP_HEADERS, environ_base=PHONE_ON_AP)
	assert r.status_code == 200 and r.get_json()['ok']
	queued = json.loads(store.r.lists['wifi:requests'][0])
	assert queued['ssid'] == 'Casa' and queued['password'] == 'nuovapassword'
	r = c.post('/wifi/request', json={'action': 'forget', 'name': 'pifire-Casa'}, headers=AP_HEADERS, environ_base=PHONE_ON_AP)
	assert r.status_code == 400
	assert store.client_seen() > 0


def test_request_validation(app_and_store):
	app, _ = app_and_store
	c = app.test_client()
	assert c.post('/wifi/request', json={'action': 'connect', 'ssid': 'Casa', 'password': 'corta'}).status_code == 400
	assert c.post('/wifi/request', json={'action': 'connect', 'ssid': ''}).status_code == 400
	assert c.post('/wifi/request', json={'action': 'connect', 'ssid': 'Ospiti', 'password': ''}).status_code == 200
	assert c.post('/wifi/request', json={'action': 'forget', 'name': 'netplan-wlan0-Casa'}).status_code == 400
	assert c.post('/wifi/request', json={'action': 'forget', 'name': 'pifire-Casa'}).status_code == 200
	assert c.post('/wifi/request', json={'action': 'reboot'}).status_code == 400


def test_status_never_contains_passwords(app_and_store):
	app, store = app_and_store
	c = app.test_client()
	c.post('/wifi/request', json={'action': 'add', 'ssid': 'Casa', 'password': 'nuovapassword'})
	body = c.get('/wifi/status').get_data(as_text=True)
	assert 'nuovapassword' not in body and json.loads(body)['running']
