#!/usr/bin/env python3

# *****************************************
# PiFire MQTT Remote Control
# *****************************************
#
# Description: Lets Home Assistant (or any MQTT client) change the grill
# mode, the hold temperature and Smoke Plus, with safety rules:
#
#  - Starting the grill remotely is refused unless explicitly allowed in the
#    MQTT settings (the igniter would heat with nobody next to the grill).
#  - Smoke / Hold / a new hold temperature are accepted only while the fire is
#    already burning, so a cold grill never starts feeding pellets in Hold.
#  - Shutdown is always accepted while the fire burns.
#
# Commands are published to <id>/command/<name>:
#   <id>/command/mode         Startup | Smoke | Hold | Shutdown | Monitor | Stop
#   <id>/command/setpoint     number, in the grill's units
#   <id>/command/smoke_plus   ON | OFF
#
# Accepted commands go through common.process_command, the same path as the
# PiFire API, so validation and logging are shared.
#
# *****************************************

FIRE_MODES = ('Startup', 'Reignite', 'Smoke', 'Hold', 'Recipe')
COOKING_MODES = ('Smoke', 'Hold')
IDLE_MODES = ('Stop', 'Monitor', 'Error')

# Every mode PiFire can report, so Home Assistant can always show the state
ALL_MODES = ['Stop', 'Startup', 'Reignite', 'Smoke', 'Hold', 'Shutdown', 'Monitor', 'Prime', 'Manual', 'Recipe', 'Error']

SETPOINT_LIMITS = {'F': (150, 500), 'C': (65, 260)}


def handle_command(command, payload, control, mqtt_settings, units):
	'''
	Decide what to do with one MQTT command.

	:param command: last part of the topic (mode, setpoint, smoke_plus)
	:param payload: message payload as text
	:param control: current PiFire control dictionary
	:param mqtt_settings: settings['notify_services']['mqtt']
	:param units: 'F' or 'C'
	:return: (arglist for process_command('set', ...), None) or (None, reason it was refused)
	'''
	if not mqtt_settings.get('control', False):
		return None, 'Remote control over MQTT is disabled in the PiFire settings.'

	mode = control.get('mode', 'Stop')
	payload = (payload or '').strip()

	if command == 'setpoint':
		try:
			value = float(payload)
		except ValueError:
			return None, f'Hold temperature "{payload}" is not a number.'
		low, high = SETPOINT_LIMITS.get(units, SETPOINT_LIMITS['F'])
		if not low <= value <= high:
			return None, f'Hold temperature must be between {low} and {high} °{units}.'
		if mode not in COOKING_MODES:
			return None, f'Hold temperature can be changed only while smoking or holding (now: {mode}).'
		return ['psp', f'{value:g}'], None

	if command == 'smoke_plus':
		if payload.upper() not in ('ON', 'OFF', 'TRUE', 'FALSE'):
			return None, f'Smoke Plus command "{payload}" not recognised (use ON or OFF).'
		return ['splus', 'true' if payload.upper() in ('ON', 'TRUE') else 'false'], None

	if command == 'mode':
		wanted = payload.capitalize()
		if wanted == mode:
			return None, f'Grill is already in {mode}.'
		if wanted == 'Startup':
			if not mqtt_settings.get('allow_remote_startup', False):
				return None, 'Starting the grill remotely is disabled in the PiFire settings.'
			if mode not in IDLE_MODES:
				return None, f'Startup is possible only from Stop or Monitor (now: {mode}).'
			return ['mode', 'startup'], None
		if wanted == 'Smoke':
			if mode not in FIRE_MODES:
				return None, f'Smoke needs a lit fire: start the grill first (now: {mode}).'
			return ['mode', 'smoke'], None
		if wanted == 'Hold':
			if mode not in FIRE_MODES:
				return None, f'Hold needs a lit fire: start the grill first (now: {mode}).'
			setpoint = control.get('primary_setpoint', 0) or 0
			if setpoint <= 0:
				return None, 'Set a hold temperature first.'
			return ['mode', 'hold', f'{setpoint:g}'], None
		if wanted == 'Shutdown':
			if mode not in FIRE_MODES:
				return None, f'Nothing to shut down (now: {mode}).'
			return ['mode', 'shutdown'], None
		if wanted == 'Monitor':
			if mode != 'Stop':
				return None, f'Monitor is possible only from Stop (now: {mode}).'
			return ['mode', 'monitor'], None
		if wanted == 'Stop':
			if mode in FIRE_MODES:
				return None, 'The fire is burning: use Shutdown, which burns off the pellets safely.'
			return ['mode', 'stop'], None
		return None, f'Mode "{payload}" cannot be set remotely.'

	return None, f'Unknown command "{command}".'


def discovery_entities(pifire_id, device, availability, units):
	'''
	Home Assistant MQTT discovery for the controllable entities.
	Returns a list of (component, object_id, config dict).
	State comes from the <id>/control topic that PiFire already publishes.
	'''
	state_topic = f'{pifire_id}/control'
	low, high = SETPOINT_LIMITS.get(units, SETPOINT_LIMITS['F'])
	common = {'device': device, 'availability': availability, 'availability_mode': 'all'}
	return [
		('select', 'grill_mode', dict(common,
			name='Grill Mode',
			unique_id=f'{pifire_id}_grill_mode'.lower(),
			object_id=f'{pifire_id}_grill_mode'.lower(),
			icon='mdi:grill',
			state_topic=state_topic,
			value_template='{{ value_json.mode }}',
			command_topic=f'{pifire_id}/command/mode',
			options=ALL_MODES)),
		('number', 'hold_temperature', dict(common,
			name='Hold Temperature',
			unique_id=f'{pifire_id}_hold_temperature'.lower(),
			object_id=f'{pifire_id}_hold_temperature'.lower(),
			device_class='temperature',
			unit_of_measurement=f'°{units}',
			min=low, max=high, step=1 if units == 'F' else 0.5, mode='box',
			state_topic=state_topic,
			value_template='{{ value_json.primary_setpoint }}',
			command_topic=f'{pifire_id}/command/setpoint')),
		('switch', 'smoke_plus', dict(common,
			name='Smoke Plus',
			unique_id=f'{pifire_id}_smoke_plus_switch'.lower(),
			object_id=f'{pifire_id}_smoke_plus_switch'.lower(),
			icon='mdi:weather-fog',
			state_topic=state_topic,
			value_template="{{ 'ON' if value_json.s_plus else 'OFF' }}",
			command_topic=f'{pifire_id}/command/smoke_plus',
			payload_on='ON', payload_off='OFF')),
	]
