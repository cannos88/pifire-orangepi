'''
Controller tests: same behaviour in Celsius and Fahrenheit, no derivative
kick on the first update.

Run from the repository root:  python -m pytest tests/control
'''

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from tools.grill_sim import harness  # noqa: E402  (also silences the controller loggers)

PID_CONTROLLERS = ['pid', 'pid_ac', 'pid_sp', 'pid_clamping', 'pid_clamping_percent_pb', 'pid_parallel']


def make(name, units):
	import importlib
	module = importlib.import_module(f'controller.{name}')
	clock = harness.SimClock()
	module.time = clock
	config, cycle = harness.load_controller_defaults(name)
	cycle_data = {'HoldCycleTime': cycle['cycle_time'], 'u_min': cycle['cycle_ratio_min'], 'u_max': cycle['cycle_ratio_max']}
	return module.Controller(config, units, cycle_data), clock


def c_to_f(c):
	return c * 9 / 5 + 32


@pytest.mark.parametrize('name', PID_CONTROLLERS)
def test_same_output_in_celsius_and_fahrenheit(name):
	ctrl_f, clock_f = make(name, 'F')
	ctrl_c, clock_c = make(name, 'C')
	setpoint_c = 110
	ctrl_f.set_target(c_to_f(setpoint_c))
	ctrl_c.set_target(setpoint_c)
	# Heat-up, overshoot and settling, one controller update every 25 s
	temps_c = [60, 75, 88, 97, 104, 109, 113, 115, 114, 112, 110, 109, 108.5, 109.5, 110.2, 110]
	for temp_c in temps_c:
		clock_f.sleep(25)
		clock_c.sleep(25)
		u_f = ctrl_f.update(c_to_f(temp_c))
		u_c = ctrl_c.update(temp_c)
		assert u_c == pytest.approx(u_f, abs=1e-9), (name, temp_c)


@pytest.mark.parametrize('name', ['pid', 'pid_ac', 'pid_sp'])
def test_no_derivative_kick_on_first_update(name):
	for units, setpoint, reading in (('F', 225, 210), ('C', 107, 99)):
		ctrl, clock = make(name, units)
		ctrl.set_target(setpoint)
		clock.sleep(25)
		ctrl.update(reading)
		assert ctrl.d == 0, (name, units)
