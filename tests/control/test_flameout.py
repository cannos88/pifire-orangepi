'''
Flame-out detector tests with synthetic temperature traces.
'''

import math
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from controller.flameout import FlameoutDetector  # noqa: E402

SETPOINT_F = 225
U_MAX = 0.9


def feed(detector, trace, ratio=0.2, start=0):
	'''trace: list of temperatures, one per second.  Returns the state history.'''
	states = []
	for i, temp in enumerate(trace):
		r = ratio(i) if callable(ratio) else ratio
		states.append(detector.update(start + i, temp, SETPOINT_F, r, U_MAX))
	return states


def steady(seconds, temp=SETPOINT_F):
	return [temp + 1.5 * math.sin(i / 40) for i in range(seconds)]


def cooling(seconds, start_temp, ambient=68, tau=500):
	return [ambient + (start_temp - ambient) * math.exp(-i / tau) for i in range(seconds)]


def test_steady_hold_stays_ok():
	d = FlameoutDetector()
	assert set(feed(d, steady(3600))) == {'ok'}


def test_dead_fire_is_detected_within_minutes():
	d = FlameoutDetector()
	feed(d, steady(1200))  # learns the steady feed (0.2)
	states = feed(d, cooling(1800, SETPOINT_F), ratio=U_MAX, start=1200)
	first_suspect = states.index('suspect')
	first_flameout = states.index('flameout')
	assert first_suspect < 5 * 60
	assert first_flameout < 8 * 60
	# The feed limit is the learned steady feed (0.2), slightly raised by the first seconds of the drop
	assert 0.2 <= d.feed_limit(0.1) <= 0.3


def test_open_lid_is_not_a_flameout():
	d = FlameoutDetector()
	feed(d, steady(1200))
	# Lid open for 10 minutes: fast drop to a plateau, then recovery after closing
	lid = [158 + (SETPOINT_F - 158) * math.exp(-i / 80) for i in range(600)]
	recovery = [lid[-1] + (SETPOINT_F - lid[-1]) * (1 - math.exp(-i / 300)) for i in range(1200)]
	states = feed(d, lid + recovery, ratio=U_MAX, start=1200)
	assert 'flameout' not in states


def test_slow_live_fire_recovery_clears_suspicion():
	d = FlameoutDetector()
	feed(d, steady(1200))
	drop = cooling(160, SETPOINT_F)  # looks like a flame-out at first...
	level = [drop[-1] - 2 * (1 - math.exp(-i / 20)) for i in range(120)]  # ...levels off with the steady feed...
	rise = [level[-1] + 0.05 * i for i in range(600)]  # ...and comes back
	states = feed(d, drop + level + rise, ratio=U_MAX, start=1200)
	assert 'suspect' in states
	assert states[-1] == 'ok'
	assert 'flameout' not in states


def test_celsius_matches_fahrenheit():
	trace_f = steady(1200) + cooling(1200, SETPOINT_F)
	ratio = lambda i: 0.2 if i < 1200 else U_MAX  # noqa: E731
	f_states = feed(FlameoutDetector(units='F'), trace_f, ratio)
	d_c = FlameoutDetector(units='C')
	c_states = [d_c.update(i, (t - 32) * 5 / 9, (SETPOINT_F - 32) * 5 / 9, ratio(i), U_MAX) for i, t in enumerate(trace_f)]
	assert f_states == c_states


def test_disabled_and_inactive():
	d = FlameoutDetector(enabled=False)
	assert set(feed(d, steady(600) + cooling(1200, SETPOINT_F), ratio=U_MAX)) == {'ok'}
	d = FlameoutDetector()
	states = [d.update(i, t, SETPOINT_F, U_MAX, U_MAX, active=False) for i, t in enumerate(cooling(1200, SETPOINT_F))]
	assert set(states) == {'ok'}
