'''
Recipes in the other unit: the bundled recipes are in °F, the grill in °C.
Upstream convert_recipe_units() stopped with KeyError('settemps').
'''

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

pytest.importorskip('flask')
from file_mgmt.recipes import convert_recipe_units  # noqa: E402


def test_fahrenheit_recipe_on_celsius_grill():
	# steps as in upstream's 3-2-1 ribs example (°F): 250/350/165 °F, 0 = not set
	steps = [{'hold_temp': t, 'trigger_temps': {'primary': 0, 'food': [0, 0]}} for t in (0, 0, 250, 350, 165, 0)]
	recipe = convert_recipe_units({'steps': steps}, 'C')
	assert [step['hold_temp'] for step in recipe['steps']] == [0, 0, 121, 177, 74, 0]


def test_triggers_converted_both_ways():
	recipe = {'steps': [{'hold_temp': 110, 'trigger_temps': {'primary': 100, 'food': [93, 0]}}]}
	step = convert_recipe_units(recipe, 'F')['steps'][0]
	assert step['hold_temp'] == 230 and step['trigger_temps'] == {'primary': 212, 'food': [199, 0]}
	step = convert_recipe_units(recipe, 'C')['steps'][0]
	assert step['hold_temp'] == 110 and step['trigger_temps']['food'] == [93, 0]
