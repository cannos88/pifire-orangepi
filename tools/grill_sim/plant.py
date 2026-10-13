'''
Pellet grill model for testing PiFire's control logic without a grill.

Everything inside the model is in degrees Celsius and seconds.

  auger -> transport delay -> fire pot fuel -> combustion -> cooking chamber
                                                     ^             |
                                                  igniter       losses (+ lid)

- The auger feeds pellets only while it runs; they reach the fire pot after a
  transport delay.
- Fuel in the fire pot burns with a time constant, but never faster than the
  air the fan supplies allows (so overfeeding piles up unburnt pellets).
- When the fire is out, pellets keep piling up in the fire pot.  The igniter
  relights it after a while if there is fuel.
- The chamber is a first-order thermal mass with losses to ambient; an open
  lid multiplies the losses.
- The RTD probe has its own lag and a little noise, and PiFire averages the
  last readings (probes/temp_queue.py).

Parameters are rough figures for a Traeger Pro 22 class grill: about 70 C at
the 10 % minimum auger duty, 110 C at 18 % (about 0.2 kg of pellets per
hour), 230 C at 42 % and an air limit around 330 C, and
about a minute of delay between auger and probe.  The chamber time constant
is set so that PiFire's default PID holds about +/-4 C (+/-7 F) at 225 F, the
result PiFire documents on a real Traeger.  They are meant for comparing
control strategies, not to predict an actual cook.  Calibrate them against real
cook history (PiFire history export) once the grill is running.
'''

import collections
import random
from dataclasses import dataclass, field


@dataclass
class PlantParams:
	ambient_c: float = 20.0
	auger_feed_g_s: float = 0.3          # pellets delivered while the auger runs (PiFire default augerrate)
	transport_delay_s: float = 25.0      # auger tube to fire pot
	burn_tau_s: float = 40.0             # fire pot fuel burn-down time constant
	max_burn_g_s: float = 0.186          # air-limited combustion rate (fan at 100 %)
	heat_per_g_c: float = 1667.0         # steady-state temperature rise per g/s burnt
	chamber_tau_s: float = 500.0         # chamber thermal time constant (steel mass)
	lid_loss_factor: float = 6.0         # loss multiplier with the lid open
	ignite_time_s: float = 90.0          # igniter on with fuel present -> fire lit
	min_fuel_to_ignite_g: float = 3.0
	probe_tau_s: float = 8.0             # RTD probe lag
	probe_noise_c: float = 0.3
	probe_avg_samples: int = 10          # PiFire TempQueue length (one sample per second)


@dataclass
class PlantState:
	t: float = 0.0
	chamber_c: float = 20.0
	probe_c: float = 20.0
	fuel_g: float = 0.0
	lit: bool = False
	igniter_on_s: float = 0.0
	fed_g: float = 0.0
	lid_open: bool = False
	fan_on: bool = True
	in_transit: collections.deque = field(default_factory=collections.deque)


class PelletGrill:
	def __init__(self, params=None, seed=1):
		self.p = params or PlantParams()
		self.s = PlantState(chamber_c=self.p.ambient_c, probe_c=self.p.ambient_c)
		self._readings = collections.deque(maxlen=self.p.probe_avg_samples)
		self._rng = random.Random(seed)

	# ---- events used by the scenarios ----
	def flame_out(self):
		self.s.lit = False

	def set_lid(self, is_open):
		self.s.lid_open = is_open

	# ---- simulation ----
	def step(self, dt, auger_on, igniter_on, fan_on=True):
		p, s = self.p, self.s
		s.fan_on = fan_on

		# Auger: pellets enter the tube now and drop into the fire pot later
		if auger_on:
			fed = p.auger_feed_g_s * dt
			s.fed_g += fed
			s.in_transit.append((s.t + p.transport_delay_s, fed))
		while s.in_transit and s.in_transit[0][0] <= s.t:
			s.fuel_g += s.in_transit.popleft()[1]

		# Igniter
		if igniter_on and not s.lit:
			s.igniter_on_s += dt
			if s.igniter_on_s >= p.ignite_time_s and s.fuel_g >= p.min_fuel_to_ignite_g:
				s.lit = True
		if not igniter_on:
			s.igniter_on_s = 0.0

		# Combustion, limited by the air the fan supplies
		burn = 0.0
		if s.lit:
			air_limit = p.max_burn_g_s if fan_on else p.max_burn_g_s * 0.15
			burn = min(s.fuel_g / p.burn_tau_s, air_limit)
			s.fuel_g -= burn * dt
			if s.fuel_g < 0.05 and burn < 0.002:
				s.lit = False  # fire pot burnt out

		# Chamber temperature (first order towards the fire's steady state)
		loss_factor = p.lid_loss_factor if s.lid_open else 1.0
		target = p.ambient_c + burn * p.heat_per_g_c / loss_factor
		s.chamber_c += (target - s.chamber_c) * min(1.0, dt * loss_factor / p.chamber_tau_s)

		# Probe lag, noise and PiFire averaging
		s.probe_c += (s.chamber_c - s.probe_c) * min(1.0, dt / p.probe_tau_s)
		s.t += dt
		self._readings.append(s.probe_c + self._rng.gauss(0, p.probe_noise_c))

	def probe_reading_c(self):
		'''Temperature as PiFire sees it: averaged probe readings.'''
		if not self._readings:
			return self.s.probe_c
		return sum(self._readings) / len(self._readings)
