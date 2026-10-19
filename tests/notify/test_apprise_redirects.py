'''
Apprise notifications: no HTTP redirects (PYSEC-2026-4200) and no tokens in
the event log, which the web app shows.
'''

import os
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)


def test_apprise_without_redirects_and_masked_log(monkeypatch):
	created, logged = [], []

	class Asset:
		def __init__(self, **kw):
			self.kw = kw

	class Apprise:
		def __init__(self, asset=None):
			created.append(asset)
			self.urls = []

		def add(self, url):
			self.urls.append(url)

		def notify(self, title, body):
			return True

	fake = types.SimpleNamespace(Apprise=Apprise, AppriseAsset=Asset)
	monkeypatch.setitem(sys.modules, 'apprise', fake)
	pytest.importorskip('requests')
	sys.modules.pop('notify.notifications', None)
	import notify.notifications as notifications
	monkeypatch.setattr(notifications, 'apprise', fake)
	monkeypatch.setattr(notifications, 'create_logger', lambda *a, **k: types.SimpleNamespace(
		info=logged.append, warning=logged.append, debug=logged.append))

	settings = {'globals': {'debug_mode': False},
				'notify_services': {'apprise': {'locations': ['tgram://123456:SECRET/987', 'gotify://host/TOKEN']}}}
	notifications._send_apprise_notifications(settings, 'Grill', 'Pronto')

	assert created and created[0].kw == {'http_redirects': False}
	assert logged and 'SECRET' not in logged[0] and 'TOKEN' not in logged[0]
	assert 'tgram' in logged[0] and 'gotify' in logged[0]
