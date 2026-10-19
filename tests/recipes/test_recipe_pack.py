'''
Italian recipe pack (tools/recipes/it.json -> recipes/IT-*.pfrecipe).
Every file is up to date with its source, opens like any PiFire recipe and has
a program control.py can run on the Traeger Pro 22.
'''

import glob
import json
import os
import subprocess
import sys
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
FILES = sorted(glob.glob(os.path.join(ROOT, 'recipes', 'IT-*.pfrecipe')))
PRO22 = (82, 232)	# °C, Traeger Pro 22 hold range


def _load(path):
	with zipfile.ZipFile(path) as z:
		return {name: json.loads(z.read(f'{name}.json')) for name in ('metadata', 'recipe', 'comments', 'assets')}


def test_pack_is_built_from_source():
	source = json.load(open(os.path.join(ROOT, 'tools', 'recipes', 'it.json'), encoding='utf-8'))
	assert len(FILES) == len(source['recipes']) == 16
	result = subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'build_recipes.py'), '--check'],
							capture_output=True, text=True)
	assert result.returncode == 0, result.stdout


def test_recipes_are_valid_programs():
	ids = set()
	for path in FILES:
		data = _load(path)
		meta, recipe = data['metadata'], data['recipe']
		name = os.path.basename(path)
		assert meta['units'] == 'C' and meta['title'] and meta['id'] not in ids, name
		ids.add(meta['id'])
		assert meta['difficulty'] in ('Easy', 'Intermediate', 'Hard', 'Advanced'), name
		steps = recipe['steps']
		assert steps[0]['mode'] == 'Startup' and steps[-1]['mode'] == 'Shutdown', name
		for index, step in enumerate(steps):
			assert set(step) == {'mode', 'hold_temp', 'timer', 'trigger_temps', 'pause', 'notify', 'message'}, name
			assert len(step['trigger_temps']['food']) == meta['food_probes'], name
			if step['mode'] == 'Hold':
				assert PRO22[0] <= step['hold_temp'] <= PRO22[1], (name, index)
			if step['mode'] in ('Hold', 'Smoke'):
				# a Smoke/Hold step without a trigger would never end
				assert step['timer'] > 0 or any(step['trigger_temps']['food']) or step['trigger_temps']['primary'] > 0, (name, index)
			if step['pause']:
				assert step['notify'] and 'Continua' in step['message'], (name, index)
		for item in recipe['instructions']:
			assert 0 <= item['step'] < len(steps), name


def test_pack_opens_with_pifire_reader():
	sys.path.insert(0, ROOT)
	import pytest
	pytest.importorskip('flask')
	from file_mgmt.common import read_json_file_data
	from file_mgmt.recipes import convert_recipe_units
	for path in FILES:
		recipe, status = read_json_file_data(path, 'recipe')
		assert status == 'OK', path
		# a grill set to °F converts the pack without errors
		converted = convert_recipe_units(json.loads(json.dumps(recipe)), 'F')
		assert all(s['hold_temp'] == 0 or s['hold_temp'] > 170 for s in converted['steps'])
