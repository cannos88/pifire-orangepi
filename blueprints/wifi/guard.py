'''
Who is talking to the web app.

Phones on the open emergency network (10.42.0.x) may only use the Wi-Fi setup
page: everything else (dashboard, API, settings) is redirected there, so the
grill cannot be controlled from an open network.  The redirect also makes
phones show the "sign in to network" page by themselves (captive portal).
'''

import ipaddress

from wifi import AP_ADDRESS

EMERGENCY_NET = ipaddress.ip_network(f'{AP_ADDRESS}/24', strict=False)
ALLOWED_PREFIXES = ('/wifi', '/static/')


def client_ip(remote_addr, headers):
	'''
	The phone's address.  Behind nginx the socket peer is 127.0.0.1 and the
	real address is in X-Real-IP; the header is trusted only from localhost.
	'''
	if remote_addr in ('127.0.0.1', '::1'):
		real = headers.get('X-Real-IP') or (headers.get('X-Forwarded-For') or '').split(',')[0].strip()
		if real:
			return real
	return remote_addr or ''


def is_emergency_client(ip):
	try:
		return ipaddress.ip_address(ip) in EMERGENCY_NET and str(ip) != AP_ADDRESS
	except ValueError:
		return False


def allowed_on_emergency(path):
	return path.startswith(ALLOWED_PREFIXES)
