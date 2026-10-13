'''
Data helpers of the Modern dashboard (chart downsampling, timer, pellet estimate).
'''

import importlib.util
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
# Load the module by path: importing the blueprints.dash package needs Flask
_spec = importlib.util.spec_from_file_location('modern_data', os.path.join(ROOT, 'blueprints', 'dash', 'modern_data.py'))
md = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(md)


def history(n, start_ms=1_000_000):
	items = []
	for i in range(n):
		items.append({
			'T': start_ms + i * 3000,
			'P': {'Grill': 100 + (i % 2)},
			'F': {'Probe1': 50.0, 'Probe2': 0 if i < n // 2 else 60},
			'PSP': 110 if i >= n // 2 else 0,
			'NT': {}, 'AUX': {},
		})
	return items


def test_downsample_caps_points_and_averages():
	out = md.downsample_history(history(1800), max_points=300)
	assert len(out['T']) == 300
	assert out['T'][-1] == 1_000_000 + 1799 * 3000      # last timestamp of the last bucket
	assert out['P']['Grill'][0] == 100.5                 # 6 samples alternating 100/101
	assert out['F']['Probe1'][10] == 50.0


def test_unplugged_probe_and_missing_setpoint_become_gaps():
	out = md.downsample_history(history(600), max_points=100)
	assert out['F']['Probe2'][0] is None and out['F']['Probe2'][-1] == 60
	assert out['PSP'][0] is None and out['PSP'][-1] == 110


def test_short_history_is_kept_as_is():
	out = md.downsample_history(history(10), max_points=300)
	assert len(out['T']) == 10
	assert md.downsample_history([], 300) == {'T': [], 'PSP': [], 'P': {}, 'F': {}}
	json.dumps(out)


def test_new_probe_appearing_later():
	items = history(4)
	items[-1]['F']['Probe3'] = 40
	out = md.downsample_history(items, max_points=300)
	assert out['F']['Probe3'] == [None, None, None, 40]


def test_timer_states():
	notify = [{'type': 'timer', 'label': 'Timer', 'shutdown': True, 'keep_warm': False}]
	assert md.timer_state({'start': 0, 'end': 0, 'paused': 0}, notify, 1000)['state'] == 'idle'
	running = md.timer_state({'start': 1000, 'end': 4600, 'paused': 0}, notify, 1600)
	assert running['state'] == 'running' and running['remaining'] == 3000 and running['shutdown']
	paused = md.timer_state({'start': 1000, 'end': 4600, 'paused': 2000}, notify, 3000)
	assert paused['state'] == 'paused' and paused['remaining'] == 2600
	assert md.timer_state({'start': 1000, 'end': 4600, 'paused': 0}, notify, 5000)['state'] == 'done'


def test_pellet_estimate_counts_only_this_cook():
	metrics = [
		{'starttime': 500_000, 'augerontime': 999},     # previous cook
		{'starttime': 1_000_000, 'augerontime': 100},   # startup of this cook
		{'starttime': 1_300_000, 'augerontime': 200},   # hold
	]
	assert md.cook_pellet_estimate(metrics, 1000, 0.3) == 90
	assert md.cook_pellet_estimate(metrics, 0, 0.3) is None
