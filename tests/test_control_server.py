# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
test_control_server
"""

import codecs
import socket
import ssl
import threading

import netifaces  # type: ignore[import]
import pytest
import requests

from opsiclientd import ControlServer
from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.Events.Utilities.Generators import createEventGenerators
from opsiclientd.Opsiclientd import Opsiclientd

from .utils import default_config, opsiclient_url, opsiclientd_auth  # noqa


def test_fire_event(default_config):  # noqa
	ocd = Opsiclientd()
	createEventGenerators(ocd)
	getEventConfigs()
	controlServer = ControlServer.OpsiclientdRpcInterface(ocd)
	controlServer.fireEvent("on_demand")


def test_firing_unknown_event_raises_error():
	controlServer = ControlServer.OpsiclientdRpcInterface(None)
	with pytest.raises(ValueError):
		controlServer.fireEvent("foobar")


def test_log_reader_start_position(tmpdir):
	log_lines = 20
	for num_tail_records in (5, 10, 19, 20, 21):
		log_file = tmpdir.join("opsiclientd.log")
		with codecs.open(log_file, "w", encoding="utf-8", errors="replace") as file:
			for i in range(log_lines):
				file.write(f"[5] [2021-01-02 11:12:13.456] [opsiclientd] log line {i+1}   (opsiclientd.py:123)\n")

		lrt = ControlServer.LogReaderThread(log_file, None, num_tail_records)
		start_position = lrt._get_start_position()

		with codecs.open(log_file, "r", encoding="utf-8", errors="replace") as file:
			file.seek(start_position)
			data = file.read()
			assert data.startswith("[5]")
			assert data.count("\n") == num_tail_records if log_lines > num_tail_records else log_lines


@pytest.mark.opsiclientd_running
def test_index_page(opsiclient_url):  # noqa
	req = requests.get(f"{opsiclient_url}", verify=False)
	assert req.status_code == 200


@pytest.mark.opsiclientd_running
def test_jsonrpc_endpoints(opsiclient_url, opsiclientd_auth):  # noqa
	rpc = {"id": 1, "method": "invalid", "params": []}
	for endpoint in ("opsiclientd", "rpc"):
		response = requests.post(f"{opsiclient_url}/{endpoint}", verify=False, json=rpc)
		assert response.status_code == 401

	response = requests.post(f"{opsiclient_url}/opsiclientd", auth=opsiclientd_auth, verify=False, json=rpc)
	assert response.status_code == 200, f"auth failed: {opsiclientd_auth}"
	rpc_response = response.json()
	assert rpc_response.get("id") == rpc["id"]
	assert rpc_response.get("result") is None
	assert rpc_response.get("error") is not None


@pytest.mark.opsiclientd_running
def test_kiosk_auth(opsiclient_url):  # noqa
	# Kiosk allows connection from 127.0.0.1 without auth
	response = requests.post(f"{opsiclient_url}/kiosk", verify=False, headers={"Content-Encoding": "gzip"}, data="fail")
	assert response.status_code == 500  # Not 401
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
			assert http_code == 401  # "X-Forwarded-For" not accepted


@pytest.mark.opsiclientd_running
def test_concurrency(opsiclient_url, opsiclientd_auth):  # noqa
	rpcs = [
		{"id": 1, "method": "execute", "params": ["sleep 3; echo ok", True]},
		{"id": 2, "method": "execute", "params": ["sleep 4; echo ok", True]},
		{"id": 3, "method": "invalid", "params": []},
		{"id": 4, "method": "log_read", "params": []},
		{"id": 5, "method": "getConfig", "params": []},
	]

	def run_rpc(rpc):
		res = requests.post(f"{opsiclient_url}/opsiclientd", auth=opsiclientd_auth, verify=False, json=rpc)
		threading.current_thread().status_code = res.status_code
		threading.current_thread().response = res.json()

	threads = []
	for rpc in rpcs:
		thread = threading.Thread(target=run_rpc, args=[rpc])
		threads.append(thread)
		thread.start()

	for thread in threads:
		thread.join()
		assert thread.status_code == 200
		if thread.response["id"] == 3:
			assert thread.response["error"] is not None
		else:
			assert thread.response["error"] is None
		if thread.response["id"] in (1, 2):
			assert "ok" in thread.response["result"]
