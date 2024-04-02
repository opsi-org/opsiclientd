# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
test_control_server
"""

import time
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from httpx._models import Cookies
from starlette.websockets import WebSocketDisconnect

from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.Events.Utilities.Generators import createEventGenerators
from opsiclientd.Opsiclientd import Opsiclientd
from opsiclientd.webserver.application.log_viewer import LogReaderThread
from opsiclientd.webserver.application.main import setup_application
from opsiclientd.webserver.rpc.control import ControlInterface

from .utils import default_config, opsiclient_url, opsiclientd_auth  # noqa


def test_fire_event(default_config):  # noqa
	ocd = Opsiclientd()
	createEventGenerators(ocd)
	getEventConfigs()
	controlServer = ControlInterface(ocd)
	controlServer.fireEvent("on_demand")


def test_firing_unknown_event_raises_error() -> None:
	controlServer = ControlInterface(Opsiclientd())
	with pytest.raises(ValueError):
		controlServer.fireEvent("foobar")


def test_auth_direct(opsiclientd_url: str, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	app = setup_application(Opsiclientd())
	session_lifetime = 2
	with patch("opsiclientd.webserver.application.middleware.SESSION_LIFETIME", session_lifetime):
		with TestClient(app=app, base_url=opsiclientd_url) as test_client:
			response = test_client.get("/")
			assert response.status_code == 401

			response = test_client.get("/", auth=opsiclientd_auth)
			assert response.status_code == 200
			session_id = response.headers["set-cookie"].split(";")[0].split("=")[1].strip()
			assert len(session_id) == 32

			response = test_client.get("/")
			assert response.status_code == 200
			assert session_id == response.headers["set-cookie"].split(";")[0].split("=")[1].strip()

			test_client.cookies = Cookies()

			response = test_client.get("/")
			assert response.status_code == 401
			# New session
			assert session_id != response.headers["set-cookie"].split(";")[0].split("=")[1].strip()

			response = test_client.get("/", auth=("not", "valid"))
			assert response.status_code == 401

			response = test_client.get("/", auth=opsiclientd_auth)
			assert response.status_code == 200

			response = test_client.get("/")
			assert response.status_code == 200

			time.sleep(session_lifetime + 1)

			response = test_client.get("/")
			# Session expired
			assert response.status_code == 401


def test_max_authentication_failures(opsiclientd_url: str, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	app = setup_application(Opsiclientd())
	max_authentication_failures = 3
	client_block_time = 3
	with (
		patch("opsiclientd.webserver.application.middleware.CLIENT_BLOCK_TIME", client_block_time),
		patch("opsiclientd.webserver.application.middleware.BaseMiddleware._max_authentication_failures", max_authentication_failures),
		patch("opsiclientd.webserver.application.middleware.BaseMiddleware.get_client_address", lambda _self, _scope: ("1.2.3.4", 12345)),
	):
		with TestClient(app=app, base_url=opsiclientd_url, headers={"x-forwarded-for": "2.2.2.2"}) as test_client:
			max_authentication_failures = 3

			for _ in range(max_authentication_failures):
				response = test_client.get("/", auth=("", "12345678901234567890123456789012"))
				assert response.status_code == 401
				assert "Authentication error" in response.text

			response = test_client.get("/", auth=("", "12345678901234567890123456789012"))
			assert response.status_code == 403
			assert response.text == "Client '1.2.3.4' is blocked"

			response = test_client.get("/", auth=("", "12345678901234567890123456789012"))
			assert response.status_code == 403
			assert response.text == "Client '1.2.3.4' is blocked"

			time.sleep(client_block_time + 1)

			response = test_client.get("/", auth=("", "12345678901234567890123456789012"))
			assert response.status_code == 401
			assert "Authentication error" in response.text


def test_auth_proxy(opsiclientd_url: str, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	app = setup_application(Opsiclientd())
	with patch("opsiclientd.webserver.application.middleware.BaseMiddleware.get_client_address", lambda _self, _scope: ("1.2.3.4", 12345)):
		with TestClient(app=app, base_url=opsiclientd_url, headers={"x-forwarded-for": "127.0.0.1"}) as test_client:
			response = test_client.get("/")
			assert response.status_code == 401

			response = test_client.get("/", auth=opsiclientd_auth)
			assert response.status_code == 200


def test_log_viewer_auth(opsiclientd_url: str, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	app = setup_application(Opsiclientd())
	with TestClient(app=app, base_url=opsiclientd_url, headers={"x-forwarded-for": "127.0.0.1"}) as test_client:
		response = test_client.get("/log_viewer")
		assert response.status_code == 401

		with pytest.raises(WebSocketDisconnect, match="Authorization header missing"):
			with test_client.websocket_connect("/log_viewer/ws"):
				pass

		response = test_client.get("/log_viewer", auth=opsiclientd_auth)
		assert response.status_code == 200
		cookie = list(test_client.cookies.jar)[0]
		with test_client.websocket_connect("/log_viewer/ws", headers={"Cookie": f"{cookie.name}={cookie.value}"}):
			pass


def test_log_reader_start_position(tmp_path: Path) -> None:
	log_lines = 20
	for num_tail_records in (5, 10, 19, 20, 21):
		log_file = tmp_path / "opsiclientd.log"
		with open(log_file, "w", encoding="utf-8", errors="replace") as file:
			for idx in range(log_lines):
				file.write(f"[5] [2021-01-02 11:12:13.456] [opsiclientd] log line {idx+1}   (opsiclientd.py:123)\n")

		lrt = LogReaderThread(filename=log_file, loop=None, websocket=None, num_tail_records=num_tail_records)  # type: ignore
		start_position = lrt._get_start_position()

		with open(log_file, "r", encoding="utf-8", errors="replace") as file:
			file.seek(start_position)
			data = file.read()
			assert data.startswith("[5]")
			lines = data.count("\n")
			print(f"{lines=}, {num_tail_records=}, {log_lines=}")
			assert lines == num_tail_records if log_lines > num_tail_records else log_lines


"""
TODO

@pytest.mark.opsiclientd_running
def test_jsonrpc_endpoints(opsiclientd_url, opsiclientd_auth):
	rpc = {"id": 1, "method": "invalid", "params": []}
	for endpoint in ("opsiclientd", "rpc"):
		response = requests.post(f"{opsiclientd_url}/{endpoint}", verify=False, json=rpc)
		assert response.status_code == 401

	response = requests.post(f"{opsiclientd_url}/opsiclientd", auth=opsiclientd_auth, verify=False, json=rpc)
	assert response.status_code == 200, f"auth failed: {opsiclientd_auth}"
	rpc_response = response.json()
	assert rpc_response.get("id") == rpc["id"]
	assert rpc_response.get("result") is None
	assert rpc_response.get("error") is not None


@pytest.mark.opsiclientd_running
def test_kiosk_auth(opsiclientd_url):
	# Kiosk allows connection from 127.0.0.1 without auth
	response = requests.post(f"{opsiclientd_url}/kiosk", verify=False, headers={"Content-Encoding": "gzip"}, data="fail")
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
def test_concurrency(opsiclientd_url, opsiclientd_auth):
	rpcs = [
		{"id": 1, "method": "execute", "params": ["sleep 3; echo ok", True]},
		{"id": 2, "method": "execute", "params": ["sleep 4; echo ok", True]},
		{"id": 3, "method": "invalid", "params": []},
		{"id": 4, "method": "log_read", "params": []},
		{"id": 5, "method": "getConfig", "params": []},
	]

	def run_rpc(rpc):
		res = requests.post(f"{opsiclientd_url}/opsiclientd", auth=opsiclientd_auth, verify=False, json=rpc)
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
"""
