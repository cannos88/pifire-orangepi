'''
File names and branch names coming from the browser (fork hardening).
'''

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

from common.safe_paths import safe_join_name, safe_within  # noqa: E402


@pytest.mark.parametrize('name', ['ribs.pfrecipe', 'Pulled pork 2026.pifire', 'events.log'])
def test_plain_names_are_accepted(name):
	assert safe_join_name('./recipes/', name) == './recipes/' + name


@pytest.mark.parametrize('name', ['', '.', '..', '../settings.json', '/etc/passwd', 'a/b.pifire',
								  'x; sudo reboot', 'x\\..\\y', 'evil\x00.json', None, 42])
def test_names_leaving_the_folder_are_refused(name):
	if name == 'x; sudo reboot':
		# harmless as a file name now that nothing goes through a shell
		assert safe_join_name('./recipes/', name) == './recipes/x; sudo reboot'
	else:
		assert safe_join_name('./recipes/', name) is None


def test_paths_must_stay_inside_the_history_folder(tmp_path, monkeypatch):
	monkeypatch.chdir(tmp_path)
	os.makedirs('history')
	assert safe_within('./history/cook.pifire', './history/') == './history/cook.pifire'
	assert safe_within('history/sub/cook.pifire', './history/')
	assert safe_within('./history/../settings.json', './history/') is None
	assert safe_within('/etc/passwd', './history/') is None
	assert safe_within('./history/', './history/') is None
	assert safe_within('./historyx/cook.pifire', './history/') is None


def test_update_branch_validation(monkeypatch):
	pytest.importorskip('flask')
	pytest.importorskip('redis')
	import blueprints.update.routes as routes
	monkeypatch.setattr(routes, 'get_available_branches', lambda: (['orangepi-dev', 'orangepi-stable', 'main'], ''))
	assert routes.valid_branch('orangepi-stable')
	for bad in ['orangepi-dev; reboot', '$(reboot)', '--help', '../x', 'unknown', '']:
		assert not routes.valid_branch(bad)
