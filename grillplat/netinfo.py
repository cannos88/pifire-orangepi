'''
IP and MAC address of every network interface, with psutil (already a PiFire
dependency).  Replaces netifaces, unmaintained since 2021 and built from
source on every install (Orange Pi fork).
'''

import socket

import psutil


def interfaces_info():
	''' {iface: {'ip_address': ..., 'mac_address': ...}} like the old netifaces code '''
	info = {}
	for iface, addrs in psutil.net_if_addrs().items():
		ip_addr, mac_addr = 'N/A', 'N/A'
		for addr in addrs:
			if addr.family == socket.AF_INET and ip_addr == 'N/A':
				ip_addr = addr.address
			elif addr.family == psutil.AF_LINK and mac_addr == 'N/A':
				mac_addr = addr.address
		info[iface] = {'ip_address': ip_addr, 'mac_address': mac_addr}
	return info
