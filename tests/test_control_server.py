# -*- coding: utf-8 -*-

import pytest
import ssl
import socket
import requests
import netifaces

from opsiclientd import ControlServer
from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.Events.Utilities.Generators import createEventGenerators

@pytest.fixture
def prepared_config(config, configFile):
	config.set('global', 'config_file', configFile)
	yield config

def test_fire_event(prepared_config): # pylint: disable=redefined-outer-name
	prepared_config.readConfigFile()

	createEventGenerators(None)
	getEventConfigs()

	controlServer = ControlServer.OpsiclientdRpcInterface(None)
	controlServer.fireEvent('on_demand')

def test_firing_unknown_event_raises_error(prepared_config): # pylint: disable=redefined-outer-name
	prepared_config.readConfigFile()

	controlServer = ControlServer.OpsiclientdRpcInterface(None)
	with pytest.raises(ValueError):
		controlServer.fireEvent('foobar')


def test_gui_startup_event_on_windows_only(prepared_config, onWindows): # pylint: disable=redefined-outer-name
	prepared_config.readConfigFile()

	createEventGenerators(None)
	configs = getEventConfigs()

	assert configs
	if onWindows:
		assert 'gui_startup' in configs

# Tests using running opsiclientd
def test_index_page(opsiclient_url):
	req = requests.get(f"{opsiclient_url}", verify=False)
	assert req.status_code == 200

def test_jsonrpc_endpoints(opsiclient_url, opsiclientd_auth, configFile):
	rpc = {"id":1, "method": "invalid", "params":[]}
	for endpoint in ("opsiclientd", "rpc"):
		response = requests.post(f"{opsiclient_url}/{endpoint}", verify=False, json=rpc)
		assert response.status_code == 401

	response = requests.post(f"{opsiclient_url}/opsiclientd", auth=opsiclientd_auth, verify=False, json=rpc)
	assert response.status_code == 200, f"auth failed: {opsiclientd_auth} / {configFile}"
	rpc_response = response.json()
	assert rpc_response.get("id") == rpc["id"]
	assert rpc_response.get("result") is None
	assert rpc_response.get("error") is not None

def test_kiosk_auth(opsiclient_url):
	# Kiosk allows connection from 127.0.0.1 without auth
	response = requests.post(
		f"{opsiclient_url}/kiosk",
		verify=False,
		headers={"Content-Encoding": "gzip"},
		data="fail"
	)
	assert response.status_code == 500 # Not 401
	assert "Not a gzipped file" in response.text

	# "X-Forwarded-For" must not be accepted
	address = None
	interfaces = netifaces.interfaces()
	for interface in interfaces:
		addresses = netifaces.ifaddresses(interface)
		addr = addresses.get(netifaces.AF_INET, [{}])[0].get("addr")
		if addr and addr != "127.0.0.1":
			address = addr
			break
	assert address is not None, "Failed to find non loopback ip address"

	with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
		context = ssl.create_default_context()
		context.check_hostname = False
		context.verify_mode = ssl.CERT_NONE
		with context.wrap_socket(sock) as ssock:
			ssock.connect((address, 4441))
			ssock.send(
				b"POST /kiosk HTTP/1.1\r\n"
				b"Accept-Encoding: data/json\r\n"
				b"Content-Encoding: gzip\r\n"
				b"X-Forwarded-For: 127.0.0.1\r\n"
				b"Content-length: 8\r\n"
				b"\r\n"
				b"xxxxxxxx"
			)
			http_code = int(ssock.recv(1024).split(b" ", 2)[1])
			assert http_code == 401 # "X-Forwarded-For" not accepted

