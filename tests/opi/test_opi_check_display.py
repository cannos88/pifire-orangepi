'''
opi_check.py: HDMI mode and touch screen of the MPI5006 display (1024x600).
'''

import importlib.util
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
_spec = importlib.util.spec_from_file_location('opi_check', os.path.join(ROOT, 'auto-install', 'orangepi', 'opi_check.py'))
opi_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(opi_check)


def test_hdmi_connectors(tmp_path):
	card = tmp_path / 'card0-HDMI-A-1'
	card.mkdir()
	(card / 'status').write_text('connected\n')
	(card / 'modes').write_text('1024x600\n800x600\n640x480\n')
	(tmp_path / 'card0-HDMI-A-2').mkdir()
	(tmp_path / 'card0-HDMI-A-2' / 'status').write_text('disconnected\n')
	result = opi_check.hdmi_connectors(str(tmp_path))
	assert result[0] == ('card0-HDMI-A-1', 'connected', ['1024x600', '800x600', '640x480'])
	assert result[1] == ('card0-HDMI-A-2', 'disconnected', [])
	assert opi_check.DISPLAY_MODE == '1024x600'


def test_touch_devices(tmp_path):
	devices = tmp_path / 'devices'
	devices.write_text('I: Bus=0003\nN: Name="wch.cn USB2IIC_CTP_CONTROL"\n\n'
					   'I: Bus=0003\nN: Name="ILITEK ILITEK-TOUCH"\n\nN: Name="gpio-keys"\n')
	assert opi_check.touch_devices(str(devices)) == ['wch.cn USB2IIC_CTP_CONTROL', 'ILITEK ILITEK-TOUCH']
