'''
Wi-Fi management for the Orange Pi port: emergency access point and Wi-Fi
setup from the web app.

- nm.py       thin wrapper around nmcli (NetworkManager)
- manager.py  state machine: client / waiting / emergency AP / retrying
- state.py    status and requests shared with the web app through Redis
- service.py  the systemd service loop (python -m wifi.service)
'''

AP_CONNECTION = 'PiFire-Setup'   # NetworkManager connection name
AP_SSID = 'PiFire-Setup'         # open network, no password
AP_ADDRESS = '10.42.0.1'         # NetworkManager "shared" mode default
AP_NETWORK = '10.42.0.'          # /24 handed out to phones on the emergency network
AP_URL = f'http://{AP_ADDRESS}'
