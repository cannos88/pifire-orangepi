'''
Runs PiFire's real controller modules against the grill model with the same
mode sequence and auger timing as control.py:

  Startup (igniter on, smoke auger cycle) -> Hold (controller drives the
  auger cycle ratio) -> Reignite when a safety check trips -> back to Hold.

Controllers are imported from controller/ and read a simulated clock, so an
hour of cooking takes a fraction of a second.
'''

import importlib
import json
import logging
import os
import sys
from dataclasses import dataclass, field

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if ROOT not in sys.path:
	sys.path.insert(0, ROOT)

# Controllers log through common.create_logger, which also writes to Redis.
# Give those loggers a handler first so create_logger leaves them alone.
for _name in ('events', 'control'):
	_logger = logging.getLogger(_name)
	if not _logger.handlers:
		_logger.addHandler(logging.NullHandler())
	_logger.setLevel(logging.WARNING)
	_logger.propagate = False

from tools.grill_sim.plant import PelletGrill, PlantParams  # noqa: E402
from controller.flameout import FlameoutDetector  # noqa: E402


def f_to_c(temp_f):
	return (temp_f - 32) * 5 / 9


def c_to_f(temp_c):
	return temp_c * 9 / 5 + 32


def load_controller_defaults(name):
	with open(os.path.join(ROOT, 'controller', 'controllers.json')) as f:
		meta = json.load(f)['metadata'][name]
	config = {opt['option_name']: opt['option_default'] for opt in meta['config']}
	cycle = meta['recommendations']['cycle']
	return config, cycle


class SimClock:
	'''Stands in for the time module inside the controller modules.'''
	def __init__(self):
		self.now = 1_000_000.0

	def time(self):
		return self.now

	def sleep(self, seconds):
		self.now += seconds


@dataclass
class SimConfig:
	controller: str = 'pid'
	units: str = 'F'                    # units PiFire runs in (settings['globals']['units'])
	setpoint_c: float = 110.0
	controller_config: dict = field(default_factory=dict)  # overrides of controllers.json defaults
	cycle: dict = field(default_factory=dict)              # overrides of the recommended cycle settings
	startup_s: float = 240.0
	smoke_on_s: float = 15.0
	smoke_off_s: float = 45.0
	pmode: int = 2
	min_startup_temp_f: float = 75.0     # settings['safety'] defaults
	max_startup_temp_f: float = 100.0
	reignite_retries: int = 1
	flameout_detect: bool = False
	lid_detect: bool = False
	lid_threshold_pct: float = 15.0
	lid_pause_s: float = 60.0
	dt: float = 1.0


@dataclass
class SimResult:
	t: list = field(default_factory=list)
	temp_c: list = field(default_factory=list)        # what PiFire reads
	chamber_c: list = field(default_factory=list)
	ratio: list = field(default_factory=list)
	mode: list = field(default_factory=list)
	fuel_g: list = field(default_factory=list)
	events: list = field(default_factory=list)        # (t, text)
	fed_g: float = 0.0
	final_mode: str = ''

	def event_time(self, text):
		for t, e in self.events:
			if text in e:
				return t
		return None


class Simulation:
	def __init__(self, config=None, plant_params=None, seed=1):
		self.cfg = config or SimConfig()
		self.plant = PelletGrill(plant_params or PlantParams(), seed=seed)
		self.clock = SimClock()
		ctrl_cfg, cycle = load_controller_defaults(self.cfg.controller)
		ctrl_cfg.update(self.cfg.controller_config)
		cycle.update(self.cfg.cycle)
		self.ctrl_cfg = ctrl_cfg
		self.hold_cycle_s = cycle['cycle_time']
		self.u_min = cycle['cycle_ratio_min']
		self.u_max = cycle['cycle_ratio_max']
		self.module = importlib.import_module(f'controller.{self.cfg.controller}')
		self.module.time = self.clock
		self.result = SimResult()
		self.scheduled = []   # (t, callable, label)

	# ---- helpers ----
	def to_units(self, temp_c):
		return c_to_f(temp_c) if self.cfg.units == 'F' else temp_c

	def setpoint(self):
		return self.to_units(self.cfg.setpoint_c)

	def at(self, t, action, label):
		self.scheduled.append((t, action, label))
		self.scheduled.sort(key=lambda item: item[0])

	def _new_controller(self):
		cycle_data = {'HoldCycleTime': self.hold_cycle_s, 'u_min': self.u_min, 'u_max': self.u_max}
		ctrl = self.module.Controller(dict(self.ctrl_cfg), self.cfg.units, cycle_data)
		ctrl.set_target(self.setpoint())
		return ctrl

	def _log(self, t, text):
		self.result.events.append((t, text))

	# ---- run ----
	def run(self, duration_s):
		cfg, plant, res = self.cfg, self.plant, self.result
		t = 0.0
		mode = 'Startup'
		mode_start = 0.0
		last_hold_state = 'Hold'
		retries = cfg.reignite_retries
		startup_temp = None
		after_start_temp = None
		ctrl = None
		cycle_ratio = cfg.smoke_on_s / (cfg.smoke_on_s + cfg.smoke_off_s + cfg.pmode * 10)
		cycle_time = cfg.smoke_on_s + cfg.smoke_off_s + cfg.pmode * 10
		auger_on = True
		auger_toggle = 0.0
		controller_cycle_start = 0.0
		target_achieved = False
		lid_detected = False
		lid_expires = 0.0
		detector = None
		suspect_logged = False

		def start_mode(new_mode, now):
			nonlocal mode, mode_start, ctrl, cycle_ratio, cycle_time, auger_on, auger_toggle
			nonlocal controller_cycle_start, target_achieved, startup_temp, after_start_temp, detector, suspect_logged
			mode, mode_start = new_mode, now
			auger_on, auger_toggle = True, now
			controller_cycle_start = now
			self._log(now, f'mode {new_mode}')
			ptemp = self.to_units(plant.probe_reading_c())
			if new_mode in ('Startup', 'Reignite'):
				cycle_time = cfg.smoke_on_s + cfg.smoke_off_s + cfg.pmode * 10
				cycle_ratio = cfg.smoke_on_s / cycle_time
				lo = self.to_units(f_to_c(cfg.min_startup_temp_f))
				hi = self.to_units(f_to_c(cfg.max_startup_temp_f))
				startup_temp = int(min(max(ptemp * 0.9, lo), hi))
				after_start_temp = ptemp
			elif new_mode == 'Hold':
				cycle_time = self.hold_cycle_s
				cycle_ratio = self.u_min
				target_achieved = False
				ctrl = self._new_controller()
				detector = FlameoutDetector(units=cfg.units, enabled=cfg.flameout_detect)
				suspect_logged = False

		start_mode('Startup', 0.0)
		last_setpoint = cfg.setpoint_c
		steps = int(duration_s / cfg.dt)
		for _ in range(steps):
			while self.scheduled and self.scheduled[0][0] <= t:
				_, action, label = self.scheduled.pop(0)
				action(self)
				self._log(t, label)

			ptemp = self.to_units(plant.probe_reading_c())
			fan_on = mode in ('Startup', 'Reignite', 'Hold') and not lid_detected

			if mode in ('Startup', 'Reignite'):
				after_start_temp = ptemp
				if t - mode_start > cfg.startup_s:
					next_mode = 'Hold' if mode == 'Startup' else last_hold_state
					# Entering Hold: same check as control.py (startup failed?)
					if after_start_temp < startup_temp:
						if retries == 0:
							start_mode('Error', t)
						else:
							retries -= 1
							start_mode('Reignite', t)
					else:
						start_mode(next_mode, t)

			elif mode == 'Hold':
				if cfg.setpoint_c != last_setpoint:
					# A new set point restarts the Hold work cycle in control.py (new controller)
					last_setpoint = cfg.setpoint_c
					start_mode('Hold', t)
				if t - controller_cycle_start > cycle_time:
					pid_output = ctrl.update(ptemp)
					controller_cycle_start = t
					cycle_ratio = self.u_min if lid_detected else pid_output
					cycle_ratio = min(max(cycle_ratio, self.u_min), self.u_max)

				# Flame-out detector (new)
				state = detector.update(t, ptemp, self.setpoint(), cycle_ratio, self.u_max,
										active=target_achieved and not lid_detected)
				if state == FlameoutDetector.SUSPECT:
					cycle_ratio = min(cycle_ratio, detector.feed_limit(self.u_min))
					if not suspect_logged:
						self._log(t, 'flameout suspected: auger limited')
						suspect_logged = True
				elif suspect_logged and state == FlameoutDetector.OK:
					self._log(t, 'flameout suspicion cleared')
					suspect_logged = False

				# Target reached, lid detection (control.py logic)
				if ptemp >= self.setpoint():
					target_achieved = True
				if (target_achieved and cfg.lid_detect
						and ptemp < self.setpoint() * (100 - cfg.lid_threshold_pct) / 100):
					lid_detected = True
					lid_expires = t + cfg.lid_pause_s
					target_achieved = False
					auger_on, auger_toggle = False, t
					self._log(t, 'lid open detected')
				if lid_detected and t > lid_expires:
					lid_detected = False

				# Safety: below startup temperature, or confirmed flame-out
				flameout = state == FlameoutDetector.FLAMEOUT
				if ptemp < startup_temp or flameout:
					self._log(t, 'flameout detected' if flameout else 'below startup temperature')
					last_hold_state = 'Hold'
					if retries == 0:
						start_mode('Error', t)
					else:
						retries -= 1
						start_mode('Reignite', t)

			# Auger timing (control.py: off time, then on time, of the current cycle)
			if mode in ('Startup', 'Reignite', 'Hold') and not lid_detected:
				if not auger_on and t - auger_toggle > cycle_time * (1 - cycle_ratio):
					auger_on, auger_toggle = True, t
					if mode == 'Hold':
						cycle_time = self.hold_cycle_s
				elif auger_on and t - auger_toggle > cycle_time * cycle_ratio:
					auger_on, auger_toggle = False, t
			elif mode == 'Error':
				auger_on = False

			igniter_on = mode in ('Startup', 'Reignite')
			plant.step(cfg.dt, auger_on=auger_on, igniter_on=igniter_on, fan_on=fan_on if mode != 'Error' else False)
			t += cfg.dt
			self.clock.now = 1_000_000.0 + t

			res.t.append(t)
			res.temp_c.append(plant.probe_reading_c())
			res.chamber_c.append(plant.s.chamber_c)
			res.ratio.append(cycle_ratio if mode == 'Hold' else (0.0 if mode == 'Error' else cycle_ratio))
			res.mode.append(mode)
			res.fuel_g.append(plant.s.fuel_g)

		res.fed_g = plant.s.fed_g
		res.final_mode = mode
		return res
