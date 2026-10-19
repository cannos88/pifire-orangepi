#!/usr/bin/env python3
'''
Build the Italian recipe pack (Orange Pi fork).

tools/recipes/it.json holds the recipes as text that is easy to read and
edit; this script writes them as PiFire recipe files (recipes/*.pfrecipe,
the same zip layout file_mgmt/recipes.py creates).  The output is
reproducible: same JSON, same files (fixed ids and zip timestamps), so a
rebuild without changes leaves git clean.

	python3 tools/build_recipes.py           # write recipes/IT-*.pfrecipe
	python3 tools/build_recipes.py --check   # fail if the files are stale
'''

import argparse
import io
import json
import os
import sys
import uuid
import zipfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SOURCE = os.path.join(ROOT, 'tools', 'recipes', 'it.json')
OUT_DIR = os.path.join(ROOT, 'recipes')

# "Basi comuni" of the approved text, added as the first instruction of the
# recipes that use them
RUB_BASE = ('Rub base (circa 2 cucchiai per kg di carne): 2 parti zucchero di canna, 2 parti paprika dolce '
			'o affumicata, 1 parte sale fino, 1 parte pepe nero macinato grosso, ½ parte aglio in polvere, '
			'½ parte cipolla in polvere, ½ parte peperoncino calabrese in polvere (facoltativo).')
RUB_SPG = 'Rub SPG (manzo): 2 parti sale grosso (Kosher), 2 parti pepe nero macinato grosso (16 mesh), 1 parte aglio granulare.'

MODES = ('Startup', 'Smoke', 'Hold', 'Shutdown')
ZIP_DATE = (2026, 10, 19, 12, 0, 0)
NAMESPACE = uuid.UUID('6f1c2a3e-8d4b-4f5a-9e7c-2b1d0a9f8e71')	# stable recipe ids


def _step(spec):
	mode = spec['mode']
	if mode not in MODES:
		raise ValueError(f'unknown mode {mode}')
	msg = spec.get('msg', '')
	return {
		'mode': mode,
		'hold_temp': spec.get('temp', 0) if mode == 'Hold' else 0,
		'timer': spec.get('timer', 0),
		'trigger_temps': {'primary': spec.get('grill', 0), 'food': [spec.get('probe', 0)]},
		'pause': bool(spec.get('pause', False)),
		'notify': bool(msg),
		'message': msg,
	}


def recipe_files(recipe, author, username):
	''' The four JSON documents of one .pfrecipe '''
	steps = [_step(s) for s in recipe['steps']]
	for index, step in enumerate(steps):
		if step['mode'] in ('Smoke', 'Hold') and not (step['timer'] or step['trigger_temps']['primary']
													   or any(step['trigger_temps']['food'])):
			raise ValueError(f"{recipe['file']}: step {index} ({step['mode']}) never ends")

	names = ' '.join(name for name, _ in recipe['ingredients'])
	basics = ([RUB_BASE] if 'Rub base' in names else []) + ([RUB_SPG] if 'SPG' in names else [])
	instructions = [{'text': text, 'step': 0, 'ingredients': [], 'assets': []} for text in basics]
	for text, step in recipe['instructions']:
		if not 0 <= step < len(steps):
			raise ValueError(f"{recipe['file']}: instruction for missing step {step}")
		instructions.append({'text': text, 'step': step, 'ingredients': [], 'assets': []})

	metadata = {
		'author': author,
		'username': username,
		'id': str(uuid.uuid5(NAMESPACE, recipe['file'])),
		'title': recipe['title'],
		'description': recipe['description'],
		'image': '',
		'thumbnail': '',
		'units': 'C',
		'prep_time': recipe['prep_time'],
		'cook_time': recipe['cook_time'],
		'rating': 5,
		'difficulty': recipe['difficulty'],
		'version': '1.1.0',
		'food_probes': 1,
	}
	body = {
		'ingredients': [{'name': name, 'quantity': quantity, 'assets': []} for name, quantity in recipe['ingredients']],
		'instructions': instructions,
		'steps': steps,
	}
	return {'metadata': metadata, 'recipe': body, 'comments': [], 'assets': []}


def pack(files):
	''' Zip bytes with the layout of file_mgmt.recipes.create_recipefile() '''
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
		for name in ('assets/', 'assets/thumbs/'):
			info = zipfile.ZipInfo(name, ZIP_DATE)
			info.external_attr = 0o40755 << 16
			archive.writestr(info, '')
		for name in ('metadata', 'recipe', 'comments', 'assets'):
			info = zipfile.ZipInfo(f'{name}.json', ZIP_DATE)
			info.compress_type = zipfile.ZIP_DEFLATED
			info.external_attr = 0o644 << 16
			archive.writestr(info, json.dumps(files[name], indent=2, sort_keys=True, ensure_ascii=False))
	return buffer.getvalue()


def build():
	with open(SOURCE, encoding='utf-8') as f:
		source = json.load(f)
	out = {}
	for recipe in source['recipes']:
		out[f"{recipe['file']}.pfrecipe"] = pack(recipe_files(recipe, source['author'], source['username']))
	return out


def main():
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument('--check', action='store_true', help='only check that recipes/ is up to date')
	args = parser.parse_args()

	stale = []
	for name, data in build().items():
		path = os.path.join(OUT_DIR, name)
		current = open(path, 'rb').read() if os.path.exists(path) else None
		if current != data:
			stale.append(name)
			if not args.check:
				with open(path, 'wb') as f:
					f.write(data)
	if args.check and stale:
		print('Out of date, run tools/build_recipes.py:', ', '.join(stale))
		return 1
	print(f"{'Stale' if args.check else 'Written'}: {len(stale)} file(s)")
	return 0


if __name__ == '__main__':
	sys.exit(main())
