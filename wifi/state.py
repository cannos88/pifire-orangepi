'''
Status and requests shared between the Wi-Fi service (root) and the web app,
through the Redis database PiFire already uses.

wifi:status          JSON written by the service every few seconds
wifi:requests        list of JSON requests from the web app (connect, add, forget, scan)
wifi:ap_client_seen  last time (epoch s) a phone on the emergency network used the page
'''

import json
import time
import uuid

STATUS_KEY = 'wifi:status'
REQUEST_KEY = 'wifi:requests'
CLIENT_SEEN_KEY = 'wifi:ap_client_seen'
STATUS_MAX_AGE = 30   # seconds: older status means the service is not running


class RedisStore:
	def __init__(self, client=None):
		if client is None:
			import redis
			client = redis.StrictRedis('localhost', 6379, decode_responses=True)
		self.r = client

	# status (service -> web app)
	def write_status(self, status):
		self.r.set(STATUS_KEY, json.dumps(status))

	def read_status(self):
		raw = self.r.get(STATUS_KEY)
		if not raw:
			return None
		try:
			return json.loads(raw)
		except ValueError:
			return None

	# requests (web app -> service)
	def push_request(self, action, **fields):
		request = dict(fields, action=action, id=uuid.uuid4().hex[:8], time=time.time())
		self.r.rpush(REQUEST_KEY, json.dumps(request))
		return request['id']

	def pop_request(self):
		raw = self.r.lpop(REQUEST_KEY)
		if not raw:
			return None
		try:
			return json.loads(raw)
		except ValueError:
			return None

	# phones using the setup page on the emergency network
	def mark_client_seen(self, when=None):
		self.r.set(CLIENT_SEEN_KEY, str(when if when is not None else time.time()))

	def client_seen(self):
		try:
			return float(self.r.get(CLIENT_SEEN_KEY) or 0)
		except (TypeError, ValueError):
			return 0.0


def service_running(status, now=None):
	now = time.time() if now is None else now
	return bool(status) and now - status.get('updated', 0) < STATUS_MAX_AGE
