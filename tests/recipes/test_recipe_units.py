'''
Recipes in the other unit: the bundled recipes are in °F, the grill in °C.
Upstream convert_recipe_units() stopped with KeyError('settemps').
'''

import json
import os
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

import pytest  # noqa: E402

pytest.importorskip('flask')
from file_mgmt.recipes import convert_recipe_units  # noqa: E402


def _recipe(name):
	with zipfile.ZipFile(os.path.join(ROOT, 'recipes', name)) as z:
		return json.loads(z.read('recipe.json'))


def test_fahrenheit_recipe_on_celsius_grill():
	recipe = convert_recipe_units(_recipe('3-2-1-Back-Ribs.pfrecipe'), 'C')
	holds = [step['hold_temp'] for step in recipe['steps']]
	assert holds == [0, 0, 121, 177, 74, 0]	# 250/350/165 °F, 0 = not set


def test_triggers_converted_both_ways():
	recipe = {'steps': [{'hold_temp': 110, 'trigger_temps': {'primary': 100, 'food': [93, 0]}}]}
	step = convert_recipe_units(recipe, 'F')['steps'][0]
	assert step['hold_temp'] == 230 and step['trigger_temps'] == {'primary': 212, 'food': [199, 0]}
	step = convert_recipe_units(recipe, 'C')['steps'][0]
	assert step['hold_temp'] == 110 and step['trigger_temps']['food'] == [93, 0]
