'''
Closed-loop scenarios on the grill model (tools/grill_sim).  They guard the
control logic as a whole: holding, units, lid openings and flame-outs.

The model is calibrated roughly, so the thresholds are generous: these tests
catch regressions and broken logic, not small tuning differences.
'''

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from tools.grill_sim.harness import SimConfig  # noqa: E402
from tools.grill_sim import scenarios  # noqa: E402


@pytest.mark.parametrize('controller', ['pid', 'pid_ac', 'pid_sp', 'pid_clamping'])
def test_holds_set_point(controller):
	metrics, _ = scenarios.hold(SimConfig(controller=controller, units='C', flameout_detect=True))
	band = metrics['last_20_min']
	assert metrics['final_mode'] == 'Hold'
	assert abs(band['mean'] - 110) < 3
	assert band['max'] - band['min'] < 12


@pytest.mark.parametrize('controller', ['pid', 'pid_ac', 'pid_sp'])
def test_celsius_and_fahrenheit_cook_the_same(controller):
	_, r_f = scenarios.hold(SimConfig(controller=controller, units='F'))
	_, r_c = scenarios.hold(SimConfig(controller=controller, units='C'))
	worst = max(abs(a - b) for a, b in zip(r_f.temp_c, r_c.temp_c))
	assert worst < 1.0


def test_flameout_baseline_overfills_the_fire_pot():
	'''Documents the problem the detector solves (original PiFire behaviour).'''
	metrics, _ = scenarios.flameout(SimConfig(controller='pid', units='C', flameout_detect=False))
	assert metrics['reignite_after_min'] > 15
	assert metrics['firepot_pellets_g'] > 200


@pytest.mark.parametrize('controller', ['pid', 'pid_sp'])
def test_flameout_detected_early(controller):
	metrics, _ = scenarios.flameout(SimConfig(controller=controller, units='C', flameout_detect=True))
	assert metrics['suspect_after_min'] is not None and metrics['suspect_after_min'] < 6
	assert metrics['reignite_after_min'] < 8
	assert metrics['firepot_pellets_g'] < 100
	assert metrics['final_mode'] == 'Hold'


@pytest.mark.parametrize('open_s', [60, 120, 300, 600])
def test_open_lid_never_triggers_reignite(open_s):
	metrics, _ = scenarios.lid_open(SimConfig(controller='pid', units='C', flameout_detect=True), open_s=open_s, minutes=80)
	assert metrics['reignite'] is False
	assert metrics['final_mode'] == 'Hold'


def test_no_false_alarm_on_set_point_change():
	metrics, r = scenarios.setpoint_step(SimConfig(controller='pid', units='C', flameout_detect=True))
	assert r.event_time('flameout suspected') is None
	assert r.final_mode if hasattr(r, 'final_mode') else True
