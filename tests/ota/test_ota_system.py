'''
auto-install/orangepi/ota-system.sh: the supervisor configs it copies keep the
user PiFire runs as (the repo copies have no user= line; without it supervisor
would start the web app and the controller as root).
'''

import os
import shutil
import subprocess

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SCRIPT = os.path.join(ROOT, 'auto-install', 'orangepi', 'ota-system.sh')


def _run(tmp_path, existing_user=None):
	pifire = tmp_path / 'pifire'
	shutil.copytree(os.path.join(ROOT, 'auto-install', 'supervisor'), pifire / 'auto-install' / 'supervisor')
	(pifire / '.venv' / 'bin').mkdir(parents=True)
	py = pifire / '.venv' / 'bin' / 'python'
	py.write_text('#!/bin/sh\n'); py.chmod(0o755)
	conf = tmp_path / 'conf.d'
	conf.mkdir()
	if existing_user:
		(conf / 'webapp.conf').write_text(f'[program:webapp]\ncommand=old\nuser={existing_user}\n')
	env = dict(os.environ, PIFIRE_DIR=str(pifire), SUPERVISOR_DIR=str(conf), PATH='/usr/bin:/bin')
	subprocess.run(['bash', SCRIPT], env=env, check=True, capture_output=True)
	return conf


def test_keeps_configured_user(tmp_path):
	conf = _run(tmp_path, existing_user='pifire')
	for name in ('webapp.conf', 'control.conf'):
		text = (conf / name).read_text()
		assert text.count('user=') == 1 and text.rstrip().endswith('user=pifire')
	assert '--threads 50' in (conf / 'webapp.conf').read_text()


def test_falls_back_to_folder_owner(tmp_path):
	conf = _run(tmp_path)
	owner = subprocess.run(['stat', '-c', '%U', str(tmp_path / 'pifire')], capture_output=True, text=True).stdout.strip()
	assert (conf / 'webapp.conf').read_text().rstrip().endswith(f'user={owner}')
