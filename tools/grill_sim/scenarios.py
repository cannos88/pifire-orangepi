'''
Standard scenarios for comparing PiFire control strategies in the simulator.

Each scenario returns a dict of metrics (temperatures in C, times in minutes,
pellets in grams) plus the raw SimResult for plotting.
'''

import statistics

from tools.grill_sim.harness import Simulation, SimConfig

FLAMEOUT_AT_S = 40 * 60
LID_AT_S = 45 * 60


def _hold_band(result, start_s, end_s=None):
	temps = [T for t, T, m in zip(result.t, result.temp_c, result.mode)
			 if m == 'Hold' and t >= start_s and (end_s is None or t < end_s)]
	if not temps:
		return None
	return {
		'mean': round(statistics.mean(temps), 1),
		'min': round(min(temps), 1),
		'max': round(max(temps), 1),
		'sd': round(statistics.pstdev(temps), 2),
	}


def hold(config, minutes=60, setpoint_c=110.0):
	'''Startup, then hold the set point.'''
	config.setpoint_c = setpoint_c
	sim = Simulation(config)
	r = sim.run(minutes * 60)
	hold_temps = [(t, T) for t, T, m in zip(r.t, r.temp_c, r.mode) if m == 'Hold']
	reached = next((t for t, T in hold_temps if T >= setpoint_c - 2), None)
	return {
		'overshoot_c': round(max(T for _, T in hold_temps) - setpoint_c, 1),
		'reach_min': round(reached / 60, 1) if reached else None,
		'last_20_min': _hold_band(r, (minutes - 20) * 60),
		'pellets_g': round(r.fed_g),
		'final_mode': r.final_mode,
	}, r


def setpoint_step(config, from_c=110.0, to_c=180.0, step_at_min=40, minutes=80):
	'''Hold, then raise the set point (new controller target, as control.py does).'''
	config.setpoint_c = from_c
	sim = Simulation(config)

	def change(s):
		s.cfg.setpoint_c = to_c
	sim.at(step_at_min * 60, change, f'set point {to_c} C')
	# The harness re-enters Hold with a new controller, as control.py does on a set point change
	r = sim.run(minutes * 60)
	after = [(t, T) for t, T in zip(r.t, r.temp_c) if t >= step_at_min * 60]
	reached = next((t for t, T in after if T >= to_c - 2), None)
	return {
		'overshoot_c': round(max(T for _, T in after) - to_c, 1),
		'reach_min': round((reached - step_at_min * 60) / 60, 1) if reached else None,
		'last_15_min': _hold_band(r, (minutes - 15) * 60),
	}, r


def lid_open(config, open_s=120, minutes=70):
	'''Lid opened for a while after the grill is holding.'''
	config.setpoint_c = 110.0
	sim = Simulation(config)
	sim.at(LID_AT_S, lambda s: s.plant.set_lid(True), 'lid opened')
	sim.at(LID_AT_S + open_s, lambda s: s.plant.set_lid(False), 'lid closed')
	r = sim.run(minutes * 60)
	after = [(t, T) for t, T in zip(r.t, r.temp_c) if t >= LID_AT_S]
	recovered = next((t for t, T in after if t > LID_AT_S + open_s and T >= 108), None)
	return {
		'min_c': round(min(T for _, T in after), 1),
		'overshoot_c': round(max(T for _, T in after) - 110.0, 1),
		'recover_min': round((recovered - LID_AT_S) / 60, 1) if recovered else None,
		'reignite': r.event_time('mode Reignite') is not None,
		'suspect': r.event_time('flameout suspected') is not None,
		'final_mode': r.final_mode,
	}, r


def flameout(config, minutes=100):
	'''The fire goes out while holding; measure how PiFire reacts.'''
	config.setpoint_c = 110.0
	sim = Simulation(config)
	sim.at(FLAMEOUT_AT_S, lambda s: s.plant.flame_out(), 'fire out')

	r = sim.run(minutes * 60)
	reignite_t = r.event_time('mode Reignite')
	# fuel in the fire pot when the fire relit (first time it is lit after the reignite)
	relight_fuel = None
	peak_after = None
	if reignite_t is not None:
		idx = r.t.index(next(t for t in r.t if t >= reignite_t))
		relight_fuel = round(max(r.fuel_g[idx:idx + 200]), 1)
		peak_after = round(max(r.chamber_c[idx:]), 1)
	suspect_t = r.event_time('flameout suspected')
	return {
		'suspect_after_min': round((suspect_t - FLAMEOUT_AT_S) / 60, 1) if suspect_t else None,
		'reignite_after_min': round((reignite_t - FLAMEOUT_AT_S) / 60, 1) if reignite_t else None,
		'temp_at_reignite_c': round(r.temp_c[r.t.index(next(t for t in r.t if t >= reignite_t))], 1) if reignite_t else None,
		'firepot_pellets_g': relight_fuel,
		'peak_after_relight_c': peak_after,
		'final_mode': r.final_mode,
	}, r


SCENARIOS = {
	'hold': hold,
	'setpoint_step': setpoint_step,
	'lid_open': lid_open,
	'flameout': flameout,
}


def run(name, **config_kwargs):
	return SCENARIOS[name](SimConfig(**config_kwargs))
