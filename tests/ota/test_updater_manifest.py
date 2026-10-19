'''
OTA updates: a grill updated from the web app only installs the libraries and
runs the system steps listed in updater/updater_manifest.json for builds newer
than its own.  A pin changed in auto-install/requirements.txt without a new
manifest entry would reach new installs but never the grill already in use.
'''

import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))


def norm(name):
	return re.sub(r'[-_.]+', '-', name).lower()


def manifest():
	with open(os.path.join(ROOT, 'updater', 'updater_manifest.json')) as f:
		return json.load(f)


def requirement_pins():
	pins = {}
	with open(os.path.join(ROOT, 'auto-install', 'requirements.txt')) as f:
		for line in f:
			line = line.split('#', 1)[0].strip()
			if '==' in line:
				name, version = line.split('==', 1)
				pins[norm(name.split('[', 1)[0])] = version.strip()  # drop extras: influxdb_client[ciso]
	return pins


def test_metadata_build_is_the_newest_entry():
	m = manifest()
	newest = max(v['build'] for v in m['versions'])
	assert m['metadata']['versions']['build'] == newest


def test_requirement_pins_reach_installed_grills():
	''' The newest pinned mention of each package in the manifest matches requirements.txt '''
	m = manifest()
	latest = {}
	for entry in sorted(m['versions'], key=lambda v: v['build']):
		for section in entry['dependencies'].values():
			for dep in section['py_dependencies']:
				if '==' in dep:
					name, version = dep.split('==', 1)
					latest[norm(name.split('[', 1)[0])] = version
	pins = requirement_pins()
	stale = {name: (pins[name], latest[name]) for name in pins if name in latest and latest[name] != pins[name]}
	assert not stale, f'add a manifest entry (new build) for: {stale}'
	for name in ('flask', 'pillow', 'redis', 'apprise', 'gunicorn'):   # updates of this fork
		assert latest.get(name) == pins[name]


def test_ota_system_script_exists():
	for entry in manifest()['versions']:
		for section in entry['dependencies'].values():
			for command in section['command_list']:
				for arg in command:
					if arg.startswith('/usr/local/bin/pifire/auto-install/orangepi/'):
						assert os.path.exists(os.path.join(ROOT, arg.replace('/usr/local/bin/pifire/', '')))


def constraint_pins():
	pins = {}
	with open(os.path.join(ROOT, 'auto-install', 'constraints.txt')) as f:
		for line in f:
			line = line.split('#', 1)[0].strip()
			if '==' in line:
				name, version = line.split('==', 1)
				pins[norm(name)] = version.strip()
	return pins


def test_constraints_lock_the_requirements():
	''' Every pinned requirement appears in constraints.txt with the same version '''
	locked = constraint_pins()
	for name, version in requirement_pins().items():
		assert locked.get(name) == version, f'{name}: requirements {version}, constraints {locked.get(name)} (run tools/lock_dependencies.sh)'


def test_constraints_leave_debian_packages_alone():
	''' numpy/scipy come from Debian (python3-scipy); removed features leave no packages behind '''
	locked = constraint_pins()
	for name in ('numpy', 'scipy', 'pip', 'setuptools'):
		assert name not in locked
	assert 'werkzeug' in locked and 'jinja2' in locked   # indirect dependencies are locked too
	# no eventlet, scikit-learn, netifaces; no Android app (Socket.IO), Bluetooth probes,
	# Raspberry Pi, WLED (zeroconf) or InfluxDB
	for gone in ('eventlet', 'greenlet', 'scikit-learn', 'joblib', 'netifaces', 'flask-socketio',
				 'python-socketio', 'simple-websocket', 'bluepy', 'bleak', 'gpiozero', 'rpi-hardware-pwm',
				 'zeroconf', 'influxdb-client'):
		assert gone not in locked
	assert 'networkx' in locked
