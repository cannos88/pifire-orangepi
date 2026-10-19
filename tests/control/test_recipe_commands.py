'''
/api/set/recipe/continue and /api/set/recipe/next (Modern dashboard buttons).
'''

import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)

pytest.importorskip('redis')
import common.common as common  # noqa: E402


def _run(monkeypatch, control, *args):
	written = []
	monkeypatch.setattr(common, 'read_control_pending', lambda: control)
	monkeypatch.setattr(common, 'read_settings', lambda: {'globals': {'units': 'C'}})
	monkeypatch.setattr(common, 'write_control', lambda c, direct_write=False, origin='': written.append(c))
	return common.process_command(action='set', arglist=list(args), origin='test'), written


def _control(mode='Recipe', triggered=True, pause=True):
	return {'mode': mode, 'updated': False, 'recipe': {'step': 2, 'step_data': {'triggered': triggered, 'pause': pause}}}


def test_continue_only_when_waiting(monkeypatch):
	result, written = _run(monkeypatch, _control(), 'recipe', 'continue')
	assert result['result'] == 'OK' and written[-1]['recipe']['step_data']['pause'] is False

	result, written = _run(monkeypatch, _control(triggered=False), 'recipe', 'continue')
	assert result['result'] == 'ERROR' and not written


def test_next_and_no_recipe(monkeypatch):
	result, written = _run(monkeypatch, _control(triggered=False, pause=False), 'recipe', 'next')
	assert result['result'] == 'OK' and written[-1]['updated'] is True

	result, written = _run(monkeypatch, _control(mode='Hold'), 'recipe', 'next')
	assert result['result'] == 'ERROR' and not written
