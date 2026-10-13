'''
/api/set/notify/{probe}/target/{value} in °C must set the probe target, not the
grill set point (upstream bug: it wrote control['primary_setpoint']).
'''

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

common = pytest.importorskip('common.common')


@pytest.mark.parametrize('units,value,expected', [('C', '93', 93.0), ('F', '200', 200)])
def test_probe_target_does_not_touch_grill_setpoint(monkeypatch, units, value, expected):
	control = {
		'primary_setpoint': 110,
		'notify_data': [
			{'type': 'probe', 'label': 'Grill', 'target': 0, 'req': False},
			{'type': 'probe', 'label': 'Probe1', 'target': 0, 'req': False},
			{'type': 'probe_limit_high', 'label': 'Probe1', 'target': 0, 'req': False},
		],
	}
	written = []
	monkeypatch.setattr(common, 'cmdsts', type('NoQueue', (), {'lrange': lambda self, *a: []})())
	monkeypatch.setattr(common, 'read_control', lambda *a, **k: control)
	monkeypatch.setattr(common, 'read_settings', lambda *a, **k: {'globals': {'units': units}})
	monkeypatch.setattr(common, 'write_control', lambda c, **k: written.append(c))

	result = common.process_command(action='set', arglist=['notify', 'Probe1', 'target', value], origin='test')
	assert result['result'] == 'OK'
	assert control['primary_setpoint'] == 110
	assert control['notify_data'][1]['target'] == expected
	assert control['notify_data'][2]['target'] == 0
	assert written


def test_commands_in_one_cycle_do_not_undo_each_other(monkeypatch):
	'''Target then request, sent before control.py applies the queue: both must survive.'''
	import json as _json
	stored = {
		'primary_setpoint': 110,
		'notify_data': [{'type': 'probe', 'label': 'Probe1', 'target': 0, 'req': False}],
	}
	queue = []

	class FakeRedis:
		def lrange(self, key, start, end):
			return list(queue) if key == 'control:write' else []

	def queue_write(control, direct_write=False, origin='x'):
		queue.append(_json.dumps(dict(control, origin=origin)))

	monkeypatch.setattr(common, 'cmdsts', FakeRedis())
	monkeypatch.setattr(common, 'read_control', lambda *a, **k: _json.loads(_json.dumps(stored)))
	monkeypatch.setattr(common, 'read_settings', lambda *a, **k: {'globals': {'units': 'C'}})
	monkeypatch.setattr(common, 'write_control', queue_write)

	common.process_command(action='set', arglist=['notify', 'Probe1', 'target', '93'], origin='test')
	common.process_command(action='set', arglist=['notify', 'Probe1', 'req', 'true'], origin='test')

	final = _json.loads(_json.dumps(stored))
	for item in queue:  # what control.py's execute_control_writes() does
		command = _json.loads(item)
		command.pop('origin')
		final = common.deep_update(final, command)
	assert final['notify_data'][0] == {'type': 'probe', 'label': 'Probe1', 'target': 93.0, 'req': True}
