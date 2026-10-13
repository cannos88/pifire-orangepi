'''
Tests for the Orange Pi Zero 2W platform (grillplat/orangepi_zero2w.py and
grillplat/opi_gpio.py), run against fake libgpiod bindings and a fake sysfs.

Run from the repository root:  python -m pytest tests/opi
'''

import logging
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

import fake_gpiod  # noqa: E402
from grillplat import opi_gpio  # noqa: E402

# Physical pin -> Linux GPIO number for the Zero 2W, as published by Orange Pi
# in wiringOP (physToWpi_ZERO_2_W combined with pinToGpio_ZERO_2_W).  Used as
# an independent cross-check of the pin map.
WIRINGOP_ZERO2W_PHYS_TO_GPIO = {
	3: 264, 5: 263, 7: 269, 8: 224, 10: 225, 11: 226, 12: 257, 13: 227,
	15: 261, 16: 270, 18: 228, 19: 231, 21: 232, 22: 262, 23: 230, 24: 229,
	26: 233, 27: 266, 28: 265, 29: 256, 31: 271, 32: 267, 33: 268, 35: 258,
	36: 76, 37: 272, 38: 260, 40: 259,
}

# PiFire PCB v4.x.x outputs (BCM numbers, from wizard/wizard_manifest.json)
PCB_V4_OUTPUTS = {'auger': 23, 'dc_fan': 26, 'fan': 26, 'igniter': 18, 'power': 22, 'pwm': 13}
CHIP = '/dev/gpiochip0'


def offset_of(bcm):
	return opi_gpio.pin_name_to_offset(opi_gpio.bcm_to_pin_name(bcm))


def level(bcm):
	return fake_gpiod.PINS.level.get((CHIP, offset_of(bcm)))


@pytest.fixture(params=[2, 1], ids=['gpiod-v2', 'gpiod-v1'])
def gpiod(request, monkeypatch):
	module = fake_gpiod.install(request.param)
	monkeypatch.setattr(opi_gpio, 'list_gpiochips', lambda: sorted(fake_gpiod.CHIP_LABELS))
	yield module
	for name in ('gpiod', 'gpiod.line'):
		sys.modules.pop(name, None)


@pytest.fixture
def platform_module(monkeypatch):
	import grillplat.orangepi_zero2w as module
	logger = logging.getLogger('test_orangepi')
	monkeypatch.setattr(module, 'create_logger', lambda name: logger)
	return module


def make_config(**overrides):
	config = {
		'outputs': dict(PCB_V4_OUTPUTS),
		'inputs': {'selector': None, 'shutdown': 17},
		'dc_fan': False,
		'frequency': 100,
		'standalone': True,
		'triggerlevel': 'HIGH',
	}
	config.update(overrides)
	return config


# ---------- Pin map ----------

def test_pin_map_matches_wiringop():
	for physical, pin_name in opi_gpio.ZERO2W_PHYSICAL_TO_PIN.items():
		assert opi_gpio.pin_name_to_offset(pin_name) == WIRINGOP_ZERO2W_PHYS_TO_GPIO[physical], physical
	assert set(opi_gpio.ZERO2W_PHYSICAL_TO_PIN) == set(WIRINGOP_ZERO2W_PHYS_TO_GPIO)


def test_every_bcm_gpio_has_an_orange_pi_pin():
	for bcm in opi_gpio.BCM_TO_PHYSICAL:
		opi_gpio.bcm_to_pin_name(bcm)


def test_pcb_v4_relay_pins():
	assert opi_gpio.bcm_to_pin_name(23) == 'PI14'   # auger, physical 16
	assert opi_gpio.bcm_to_pin_name(18) == 'PI1'    # igniter, physical 12
	assert opi_gpio.bcm_to_pin_name(22) == 'PI5'    # power, physical 15
	assert opi_gpio.bcm_to_pin_name(26) == 'PI16'   # fan, physical 37


def test_pwm_channels():
	assert opi_gpio.bcm_to_pwm_channel(13) is None  # physical 33: no hardware PWM
	assert opi_gpio.bcm_to_pwm_channel(12) == 1     # physical 32: PWM1
	assert opi_gpio.is_console_pin(14) and opi_gpio.is_console_pin(15)
	assert not opi_gpio.is_console_pin(23)


@pytest.mark.parametrize('bad', ['PZ', 'XI1', 'PI32', 'P1', ''])
def test_invalid_pin_names(bad):
	with pytest.raises(ValueError):
		opi_gpio.pin_name_to_offset(bad)


def test_invalid_bcm():
	with pytest.raises(ValueError):
		opi_gpio.bcm_to_physical(40)


# ---------- GPIO through libgpiod ----------

def test_finds_main_pin_controller(gpiod):
	assert opi_gpio.find_main_chip(gpiod=gpiod) == CHIP


def test_relays_start_off_active_high(gpiod, platform_module):
	grill = platform_module.GrillPlatform(make_config())
	for name in ('auger', 'igniter', 'power', 'fan'):
		assert level(PCB_V4_OUTPUTS[name]) == 0, name
	assert grill.get_output_status() == {'auger': False, 'igniter': False, 'power': False, 'fan': False}

	grill.auger_on()
	grill.fan_on()
	assert level(23) == 1 and level(26) == 1
	assert grill.get_output_status()['auger'] is True

	grill.auger_off()
	grill.fan_toggle()
	assert level(23) == 0 and level(26) == 0
	grill.cleanup()
	assert not fake_gpiod.PINS.requested


def test_relays_start_off_active_low(gpiod, platform_module):
	grill = platform_module.GrillPlatform(make_config(triggerlevel='LOW'))
	# Inactive on an active-low relay board means the pin sits at 3.3 V
	assert level(23) == 1 and level(18) == 1
	grill.igniter_on()
	grill.power_on()
	assert level(18) == 0 and level(22) == 0
	status = grill.get_output_status()
	assert status['igniter'] is True and status['power'] is True and status['auger'] is False
	grill.cleanup()


def test_selector_input(gpiod, platform_module):
	grill = platform_module.GrillPlatform(make_config(standalone=False, inputs={'selector': 17, 'shutdown': 17}))
	assert grill.get_input_status() is False  # pulled up, not pressed
	fake_gpiod.PINS.inputs[(CHIP, offset_of(17))] = 0  # button shorts the pin to ground
	assert grill.get_input_status() is True
	grill.cleanup()


def test_dc_fan_rejects_pin_without_hardware_pwm(gpiod, platform_module):
	with pytest.raises(ValueError, match='pin 32'):
		platform_module.GrillPlatform(make_config(dc_fan=True))


def _fake_pwm_chip(tmp_path, channel=1):
	chip = tmp_path / 'pwmchip0'
	pwm = chip / f'pwm{channel}'
	pwm.mkdir(parents=True)
	(chip / 'npwm').write_text('6')
	(chip / 'export').write_text('')
	for name in ('period', 'duty_cycle', 'enable'):
		(pwm / name).write_text('0')
	return chip, pwm


def test_dc_fan_with_hardware_pwm(gpiod, platform_module, tmp_path):
	chip, pwm = _fake_pwm_chip(tmp_path)
	grill = platform_module.GrillPlatform(make_config(dc_fan=True, pwm_pin=12, frequency=25000, pwm_chip=str(chip)))
	assert (pwm / 'period').read_text() == '40000'

	grill.fan_on(75)  # 75 % fan speed -> 25 % PWM duty, the amplifier inverts it
	assert (pwm / 'enable').read_text() == '1'
	assert (pwm / 'duty_cycle').read_text() == '10000'
	assert level(26) == 1
	assert grill.get_output_status()['pwm'] == 75

	grill.set_duty_cycle(40)
	assert (pwm / 'duty_cycle').read_text() == '24000'
	grill.fan_off()
	assert (pwm / 'enable').read_text() == '0'
	assert level(26) == 0
	grill.cleanup()


def test_smoke_plus_ramp_ends_at_max(gpiod, platform_module, tmp_path):
	chip, pwm = _fake_pwm_chip(tmp_path)
	grill = platform_module.GrillPlatform(make_config(dc_fan=True, pwm_pin=12, frequency=25000, pwm_chip=str(chip)))
	grill._start_ramp(on_time=0.2, min_duty_cycle=20, max_duty_cycle=100, background=False)
	assert grill.current_fan_speed_percent == 100
	grill.cleanup()


# ---------- System commands ----------

def test_cpu_temp_prefers_cpu_zone(platform_module, tmp_path):
	for zone, zone_type, millideg in (('thermal_zone0', 'gpu-thermal', '41000'), ('thermal_zone1', 'cpu-thermal', '47350')):
		(tmp_path / zone).mkdir()
		(tmp_path / zone / 'type').write_text(zone_type)
		(tmp_path / zone / 'temp').write_text(millideg)
	assert platform_module.GrillPlatform._read_cpu_temp(str(tmp_path)) == pytest.approx(47.35)


def test_wifi_quality_from_proc(platform_module, tmp_path):
	proc = tmp_path / 'wireless'
	proc.write_text(
		'Inter-| sta-|   Quality        |   Discarded packets               | Missed | WE\n'
		' face | tus | link level noise |  nwid  crypt   frag  retry   misc | beacon | 22\n'
		' wlan0: 0000   49.  -61.  -256        0      0      0      0     12        0\n'
	)
	assert platform_module.GrillPlatform._read_wifi_quality('wlan0', str(proc)) == (49, 70)
	assert platform_module.GrillPlatform._read_wifi_quality('wlan1', str(proc)) is None
