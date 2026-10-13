'''
Remote control over MQTT: safety rules and handler wiring.
'''

import json
import os
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from notify.mqtt_control import handle_command, discovery_entities  # noqa: E402

ON = {'control': True, 'allow_remote_startup': False}


def ctl(mode, setpoint=110):
	return {'mode': mode, 'primary_setpoint': setpoint}


def test_disabled_by_default():
	args, reason = handle_command('mode', 'Shutdown', ctl('Hold'), {}, 'C')
	assert args is None and 'disabled' in reason


def test_remote_startup_needs_explicit_permission():
	args, reason = handle_command('mode', 'Startup', ctl('Stop'), ON, 'C')
	assert args is None and 'Starting the grill remotely' in reason
	args, _ = handle_command('mode', 'Startup', ctl('Stop'), dict(ON, allow_remote_startup=True), 'C')
	assert args == ['mode', 'startup']
	args, _ = handle_command('mode', 'Startup', ctl('Hold'), dict(ON, allow_remote_startup=True), 'C')
	assert args is None


@pytest.mark.parametrize('mode', ['Stop', 'Monitor', 'Shutdown', 'Error', 'Prime'])
def test_cold_grill_never_goes_to_hold_or_smoke(mode):
	assert handle_command('mode', 'Hold', ctl(mode), ON, 'C')[0] is None
	assert handle_command('mode', 'Smoke', ctl(mode), ON, 'C')[0] is None
	assert handle_command('setpoint', '120', ctl(mode), ON, 'C')[0] is None


def test_hold_and_setpoint_while_cooking():
	assert handle_command('mode', 'Hold', ctl('Smoke', 107.5), ON, 'C')[0] == ['mode', 'hold', '107.5']
	assert handle_command('setpoint', '135', ctl('Hold'), ON, 'C')[0] == ['psp', '135']
	assert handle_command('setpoint', '275', ctl('Hold'), ON, 'F')[0] == ['psp', '275']


@pytest.mark.parametrize('value,units', [('20', 'C'), ('300', 'C'), ('100', 'F'), ('abc', 'C')])
def test_setpoint_limits(value, units):
	assert handle_command('setpoint', value, ctl('Hold'), ON, units)[0] is None


def test_shutdown_and_stop():
	assert handle_command('mode', 'Shutdown', ctl('Hold'), ON, 'C')[0] == ['mode', 'shutdown']
	assert handle_command('mode', 'Shutdown', ctl('Stop'), ON, 'C')[0] is None
	# A burning fire is never cut with Stop: Shutdown burns the pellets off
	args, reason = handle_command('mode', 'Stop', ctl('Hold'), ON, 'C')
	assert args is None and 'Shutdown' in reason
	assert handle_command('mode', 'Stop', ctl('Monitor'), ON, 'C')[0] == ['mode', 'stop']


def test_smoke_plus():
	assert handle_command('smoke_plus', 'ON', ctl('Hold'), ON, 'C')[0] == ['splus', 'true']
	assert handle_command('smoke_plus', 'off', ctl('Hold'), ON, 'C')[0] == ['splus', 'false']
	assert handle_command('smoke_plus', 'maybe', ctl('Hold'), ON, 'C')[0] is None


def test_discovery_entities():
	entities = discovery_entities('PiFire', {'identifiers': ['PiFire']}, [{'topic': 'PiFire/availability'}], 'C')
	kinds = {component: config for component, _, config in entities}
	assert set(kinds) == {'select', 'number', 'switch'}
	assert kinds['number']['min'] == 65 and kinds['number']['max'] == 260
	assert kinds['select']['command_topic'] == 'PiFire/command/mode'
	assert 'Hold' in kinds['select']['options'] and 'Reignite' in kinds['select']['options']
	json.dumps(entities)  # must be serialisable


def test_handler_routes_commands(monkeypatch):
	pytest.importorskip('paho.mqtt.client')
	import notify.mqtt_handler as handler_module
	calls, published = [], []
	monkeypatch.setattr(handler_module, 'read_control', lambda: ctl('Hold'))
	monkeypatch.setattr(handler_module, 'process_command',
						lambda action, arglist, origin: calls.append((action, arglist, origin)) or {'result': 'OK', 'message': 'ok'})
	handler = handler_module.MqttNotificationHandler.__new__(handler_module.MqttNotificationHandler)
	handler._mqtt_settings = dict(ON, id='PiFire')
	handler._units = 'C'
	handler.pifire_id = 'PiFire'
	handler._mqttLogger = types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, exception=lambda *a: None)
	handler._publish_data = lambda topic, payload, **kw: published.append((topic, json.loads(payload)))

	msg = types.SimpleNamespace(topic='PiFire/command/setpoint', payload=b'120')
	handler._on_message(None, None, msg)
	assert calls == [('set', ['psp', '120'], 'mqtt')]
	assert published[-1][1]['result'] == 'OK'

	msg = types.SimpleNamespace(topic='PiFire/command/mode', payload=b'Startup')
	handler._on_message(None, None, msg)
	assert len(calls) == 1
	assert published[-1][0] == 'PiFire/command/result' and published[-1][1]['result'] == 'REFUSED'
