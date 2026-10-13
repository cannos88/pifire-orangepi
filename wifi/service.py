'''
PiFire Wi-Fi service: emergency network and Wi-Fi setup requests.

Runs as root under systemd (auto-install/orangepi/pifire-wifi.service):
    python -m wifi.service

Needs NetworkManager (nmcli) and the Redis server PiFire already uses.
'''

import logging
import os
import sys
import time

from .manager import WifiManager
from .nm import NetworkManagerCLI
from .state import RedisStore

TICK_S = 5


def main():
	logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', stream=sys.stdout)
	log = logging.getLogger('wifi')
	nm = NetworkManagerCLI(ifname=os.environ.get('PIFIRE_WIFI_IFACE') or None)
	if not nm.available():
		log.error('NetworkManager is not running: the emergency network needs it (run auto-install/orangepi/setup.sh).')
		return 1
	store = RedisStore()
	manager = WifiManager(nm, store, time.time,
						  grace=int(os.environ.get('PIFIRE_WIFI_GRACE', 180)))
	log.info(f'PiFire Wi-Fi service started on {nm.ifname}')
	while True:
		try:
			manager.tick()
		except Exception as exc:  # keep going: a bad nmcli answer must not stop the fallback
			log.exception(f'Wi-Fi service error: {exc}')
		time.sleep(TICK_S)


if __name__ == '__main__':
	sys.exit(main())
