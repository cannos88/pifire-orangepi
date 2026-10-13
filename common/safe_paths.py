'''
File names that come from the browser (Orange Pi fork).

Upstream PiFire built paths like f'{RECIPE_FOLDER}{filename}' from request data
and passed some of them to os.system('rm ...'): a name such as
"../settings.json" or "x; reboot" reached files and commands outside the
folder.  These helpers return a safe path, or None when the name tries to
leave its folder.
'''

import os


def safe_join_name(folder, name):
	'''
	A plain file name inside folder, e.g. ('./recipes/', 'ribs.pfrecipe').
	Rejects separators, '..', absolute paths and empty names.
	'''
	if not isinstance(name, str) or not name or '\x00' in name:
		return None
	if name in ('.', '..') or os.path.isabs(name) or os.path.basename(name) != name or '\\' in name:
		return None
	return os.path.join(folder, name)


def safe_within(path, *folders):
	'''
	A path the browser sends back as it received it (e.g. './history/cook.pifire'),
	accepted only if it resolves inside one of the folders.
	'''
	if not isinstance(path, str) or not path or '\x00' in path:
		return None
	real = os.path.realpath(path)
	for folder in folders:
		base = os.path.realpath(folder)
		if os.path.commonpath([real, base]) == base and real != base:
			return path
	return None
