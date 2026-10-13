'''
Wi-Fi setup page: /wifi

Talks to the Wi-Fi service (wifi/service.py) through Redis: the page reads
wifi:status and queues requests in wifi:requests.  Passwords are only passed
to the service, never stored by the web app or sent back to the browser.
'''

import socket

from flask import jsonify, render_template, request

from wifi.state import RedisStore, service_running
from . import wifi_bp
from .guard import client_ip, is_emergency_client

EMERGENCY_ACTIONS = ('connect', 'scan')
ALL_ACTIONS = ('connect', 'add', 'forget', 'scan')

_store = None


def store():
	global _store
	if _store is None:
		_store = RedisStore()
	return _store


def _emergency():
	return is_emergency_client(client_ip(request.remote_addr, request.headers))


def validate(payload, emergency, saved):
	''' Returns (cleaned request fields, error message). '''
	action = payload.get('action')
	allowed = EMERGENCY_ACTIONS if emergency else ALL_ACTIONS
	if action not in allowed:
		return None, 'Azione non permessa.'
	if action == 'scan':
		return {}, None
	if action == 'forget':
		name = payload.get('name') or ''
		if not any(s.get('name') == name and s.get('removable') for s in saved):
			return None, 'Rete non trovata.'
		return {'name': name}, None
	ssid = (payload.get('ssid') or '').strip()
	password = payload.get('password') or ''
	if not ssid or len(ssid.encode('utf-8')) > 32:
		return None, 'Nome della rete non valido.'
	if password and not (8 <= len(password) <= 63):
		return None, 'La password Wi-Fi deve avere da 8 a 63 caratteri.'
	return {'ssid': ssid, 'password': password}, None


@wifi_bp.route('/', methods=['GET'])
def wifi_page():
	return render_template('wifi/index.html', emergency=_emergency(), hostname=socket.gethostname())


@wifi_bp.route('/status', methods=['GET'])
def wifi_status():
	emergency = _emergency()
	try:
		st = store().read_status()
		if emergency:
			store().mark_client_seen()
	except Exception:
		st = None
	running = service_running(st)
	return jsonify({'running': running, 'emergency': emergency, 'status': st if running else None})


@wifi_bp.route('/request', methods=['POST'])
def wifi_request():
	emergency = _emergency()
	payload = request.get_json(silent=True) or {}
	try:
		st = store().read_status()
	except Exception:
		st = None
	if not service_running(st):
		return jsonify({'ok': False, 'message': 'Il servizio Wi-Fi non è attivo.'}), 503
	fields, error = validate(payload, emergency, st.get('saved', []))
	if error:
		return jsonify({'ok': False, 'message': error}), 400
	request_id = store().push_request(payload['action'], **fields)
	if emergency:
		store().mark_client_seen()
	return jsonify({'ok': True, 'id': request_id})
