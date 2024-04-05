# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
test_control_server
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import requests
from httpx import HTTPStatusError
from opsicommon.objects import ProductOnClient, serialize
from opsicommon.system.info import is_macos
from starlette.websockets import WebSocketDisconnect

from opsiclientd import __version__
from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.Events.Utilities.Generators import createEventGenerators
from opsiclientd.Opsiclientd import Opsiclientd
from opsiclientd.webserver.application.log_viewer import LogReaderThread
from opsiclientd.webserver.application.middleware import REDIRECTS
from opsiclientd.webserver.rpc.control import ControlInterface, get_cache_service_interface

from .utils import Config, OpsiclientdTestClient, default_config, get_test_client, opsiclientd_auth, opsiclientd_url, test_client  # noqa


def test_fire_event(default_config: Config) -> None:  # noqa
	ocd = Opsiclientd()
	createEventGenerators(ocd)
	getEventConfigs()
	controlServer = ControlInterface(ocd)
	controlServer.fireEvent("on_demand")


def test_firing_unknown_event_raises_error() -> None:
	controlServer = ControlInterface(Opsiclientd())
	with pytest.raises(ValueError):
		controlServer.fireEvent("foobar")


def test_redirect(test_client: OpsiclientdTestClient) -> None:  # noqa
	with test_client as client:
		for path, redirect in REDIRECTS.items():
			response = client.get(path, follow_redirects=False)
			assert response.status_code == 301
			assert response.headers["location"] == redirect


def test_auth_direct(test_client: OpsiclientdTestClient, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	session_lifetime = 2
	with patch("opsiclientd.webserver.application.middleware.SESSION_LIFETIME", session_lifetime):
		with test_client as client:
			response = client.get("/")
			assert response.status_code == 401

			response = client.get("/", auth=opsiclientd_auth)
			assert response.status_code == 200
			session_id = response.headers["set-cookie"].split(";")[0].split("=")[1].strip()
			assert len(session_id) == 32
			print(client.cookies)
			print(client.cookies.jar)

			response = client.get("/")
			assert response.status_code == 200
			assert session_id == response.headers["set-cookie"].split(";")[0].split("=")[1].strip()

			client.reset_cookies()

			response = client.get("/")
			assert response.status_code == 401
			# New session
			assert session_id != response.headers["set-cookie"].split(";")[0].split("=")[1].strip()

			response = client.get("/", auth=("not", "valid"))
			assert response.status_code == 401

			response = client.get("/", auth=opsiclientd_auth)
			assert response.status_code == 200

			response = client.get("/")
			assert response.status_code == 200

			time.sleep(session_lifetime + 1)

			response = client.get("/")
			# Session expired
			assert response.status_code == 401


def test_max_authentication_failures(test_client: OpsiclientdTestClient) -> None:  # noqa
	max_authentication_failures = 3
	client_block_time = 3
	test_client.set_client_address("1.2.3.4", 12345)
	with (
		patch("opsiclientd.webserver.application.middleware.CLIENT_BLOCK_TIME", client_block_time),
		patch("opsiclientd.webserver.application.middleware.BaseMiddleware._max_authentication_failures", max_authentication_failures),
	):
		with test_client as client:
			max_authentication_failures = 3
			auth = ("", "12345678901234567890123456789012")
			headers = {"x-forwarded-for": "2.2.2.2"}
			for _ in range(max_authentication_failures):
				response = client.get("/", auth=auth, headers=headers)
				assert response.status_code == 401
				assert "Authentication error" in response.text

			response = client.get("/", auth=auth, headers=headers)
			assert response.status_code == 403
			assert response.text == "Client '1.2.3.4' is blocked"

			response = client.get("/", auth=auth, headers=headers)
			assert response.status_code == 403
			assert response.text == "Client '1.2.3.4' is blocked"

			time.sleep(client_block_time + 1)

			response = client.get("/", auth=auth, headers=headers)
			assert response.status_code == 401
			assert "Authentication error" in response.text


def test_auth_proxy(test_client: OpsiclientdTestClient, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	test_client.set_client_address("1.2.3.4", 12345)
	with test_client as client:
		response = client.get("/", headers={"x-forwarded-for": "127.0.0.1"})
		assert response.status_code == 401

		response = client.get("/", auth=opsiclientd_auth)
		assert response.status_code == 200


def test_log_viewer_auth(test_client: OpsiclientdTestClient, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	with test_client as client:
		response = client.get("/log_viewer", headers={"x-forwarded-for": "127.0.0.1"})
		assert response.status_code == 401

		with pytest.raises(WebSocketDisconnect) as exc_info:
			with client.websocket_connect("/log_viewer/ws"):
				pass
		assert exc_info.value.code == 1008
		assert exc_info.value.reason == "Authorization header missing"

		response = client.get("/log_viewer", auth=opsiclientd_auth)
		assert response.status_code == 200
		cookie = list(client.cookies.jar)[0]
		with client.websocket_connect("/log_viewer/ws", headers={"Cookie": f"{cookie.name}={cookie.value}"}):
			pass


def test_kiosk_auth(default_config: Config, test_client: OpsiclientdTestClient) -> None:  # noqa
	# Kiosk allows connection from 127.0.0.1 without auth
	with test_client as client:
		response = client.jsonrpc20(path="/kiosk", method="getClientId", params=[], id="1")
		assert "error" not in response
		assert response["result"] == default_config.get("global", "host_id")

		test_client.set_client_address("1.2.3.4", 12345)
		with pytest.raises(HTTPStatusError, match="401 Unauthorized"):
			client.jsonrpc20(path="/kiosk", method="getClientId", params=[], id="1", headers={"x-forwarded-for": "127.0.0.1"})


def test_headers(test_client: OpsiclientdTestClient, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	with test_client as client:
		test_client.auth = opsiclientd_auth
		response = client.get("/")
		assert response.headers["server"] == f"opsiclientd {__version__}"

		server_date = response.headers["date"]
		assert server_date.endswith(" UTC")
		server_dt = datetime.strptime(server_date, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
		now = datetime.now(tz=timezone.utc)
		assert abs((now - server_dt).total_seconds()) < 2

		server_timestamp = int(response.headers["x-date-unix-timestamp"])
		assert abs(now.timestamp() - server_timestamp) < 2

		time.sleep(1)

		res = test_client.get("/")
		server_date = res.headers["date"]
		server_dt = datetime.strptime(server_date, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
		assert now < server_dt

		response = client.get("/rpc")
		assert response.headers["server"] == "opsiclientd config cache service 4.3.0.0"


def test_control_jsonrpc(test_client: OpsiclientdTestClient, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	with test_client as client:
		with pytest.raises(HTTPStatusError, match="401 Unauthorized"):
			client.jsonrpc20(path="/opsiclientd", method="noop", params=["x"], id="1")

		test_client.auth = opsiclientd_auth
		response = client.jsonrpc20(path="/opsiclientd", method="noop", params=["x"], id="2")
		assert "error" not in response
		assert response["result"] is None
		assert response["id"] == "2"

		response = client.jsonrpc20(path="/opsiclientd", method="uptime", params=[], id="3")
		assert "error" not in response
		assert int(response["result"]) >= 0
		assert response["id"] == "3"


@pytest.mark.opsiclientd_running
def test_concurrency(opsiclientd_url: str, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	if is_macos():
		# TODO: 401 on macOS
		pytest.skip("Concurrency test is not supported on macOS")

	rpcs = [
		{"id": 1, "method": "execute", "params": ["sleep 3; echo ok", True]},
		{"id": 2, "method": "execute", "params": ["sleep 4; echo ok", True]},
		{"id": 3, "method": "invalid", "params": []},
		{"id": 4, "method": "log_read", "params": []},
		{"id": 5, "method": "getConfig", "params": []},
	]

	def run_rpc(rpc: dict[str, Any]) -> None:
		thread = threading.current_thread()
		res = requests.post(f"{opsiclientd_url}/opsiclientd", auth=opsiclientd_auth, verify=False, json=rpc)
		setattr(thread, "status_code", res.status_code)
		setattr(thread, "response", res.json())

	threads = []
	for rpc in rpcs:
		thread = threading.Thread(target=run_rpc, args=[rpc])
		threads.append(thread)
		thread.start()

	for thread in threads:
		thread.join()
		assert getattr(thread, "status_code") == 200
		response = getattr(thread, "response")
		if response["id"] == 3:
			assert response["error"] is not None
		else:
			assert response["error"] is None
		if response["id"] in (1, 2):
			assert "ok" in response["result"]


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


def test_cache_service_interface(default_config: Config, tmp_path: Path) -> None:  # noqa
	default_config.set("cache_service", "extension_config_dir", str(tmp_path))
	ocd = Opsiclientd()
	with ocd.runCacheService(allow_fail=False):
		backend = get_cache_service_interface(ocd)
		interface = backend.get_interface()
		assert "backend_info" in interface
		assert "accessControl_authenticated" in interface
		assert "productOnClient_generateSequence" in interface
		assert "productOnClient_getObjectsWithSequence" in interface
		backend.productOnClient_getObjectsWithSequence()  # type: ignore[attr-defined]


def test_cache_service_jsonrpc(default_config: Config, tmp_path: Path, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	default_config.set("cache_service", "extension_config_dir", str(tmp_path))
	ocd = Opsiclientd()
	with ocd.runCacheService(allow_fail=False):
		with get_test_client(ocd) as client:
			with pytest.raises(HTTPStatusError, match="401 Unauthorized"):
				client.jsonrpc20(path="/rpc", method="backend_info", params=[], id=1)

			client.auth = opsiclientd_auth
			pocs = [
				ProductOnClient(productId="product1", productType="LocalbootProduct", clientId="client1.opsi.test"),
				ProductOnClient(productId="product2", productType="LocalbootProduct", clientId="client1.opsi.test"),
			]
			start = time.time()
			for rpc_id in range(9, 21):
				client.jsonrpc20(path="/rpc", method="productOnClient_createObjects", params=[serialize(pocs)], id=rpc_id)
			duration = time.time() - start
			print(f"Duration: {duration:.2f} seconds")
			assert duration < 3

			response = client.jsonrpc20(path="/rpc", method="productOnClient_generateSequence", params=[serialize(pocs)], id=101)
			print(response)
			assert "error" not in response
			assert response["id"] == 101

			response = client.jsonrpc20(path="/rpc", method="productOnClient_getObjectsWithSequence", params=[], id=102)


def test_upload(test_client: OpsiclientdTestClient, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	data_received = b""
	data = b"test data" * 50_000

	def self_update_from_file(self: Opsiclientd, filename: str | Path) -> None:
		nonlocal data_received
		data_received = Path(filename).read_bytes()

	with patch("opsiclientd.Opsiclientd.Opsiclientd.self_update_from_file", self_update_from_file):
		with test_client as client:
			test_client.auth = opsiclientd_auth
			response = client.post("/upload/update/opsiclientd", files={"file": ("opsiclientd.tar.gz", data)})
			assert response.status_code == 200
			assert response.text == '"ok"'
			assert data == data_received


def test_download(test_client: OpsiclientdTestClient, opsiclientd_auth: tuple[str, str]) -> None:  # noqa
	if is_macos():
		# TODO: PermissionError: [Errno 13] Permission denied: '/var/local/share/opsi-client-agent/files/logs-opsiclientd...
		pytest.skip("Download test is not supported on macOS")

	orig_collectLogfiles = Opsiclientd.collectLogfiles
	params_received = []

	def collectLogfiles(
		self: Opsiclientd, types: list[str] | None = None, max_age_days: int | None = None, timeline_db: bool = True
	) -> Path:
		nonlocal params_received
		params_received.append([types, max_age_days, timeline_db])
		return orig_collectLogfiles(self, types=types, max_age_days=max_age_days, timeline_db=timeline_db)

	with patch("opsiclientd.Opsiclientd.Opsiclientd.collectLogfiles", collectLogfiles):
		test_client.auth = opsiclientd_auth
		with test_client as client:
			response = client.get("/download/logs")
			assert response.status_code == 200
			assert response.headers["content-type"] in ("application/zip", "application/x-zip-compressed")
			assert int(response.headers["content-length"]) > 0
			assert params_received[0] == [None, None, True]

			response = client.get("/download/logs", params={"types": ["opsiclientd", "opsi-script"], "max_age_days": 10})
			assert response.status_code == 200
			assert response.headers["content-type"] in ("application/zip", "application/x-zip-compressed")
			assert int(response.headers["content-length"]) > 0
			assert params_received[1] == [["opsiclientd", "opsi-script"], 10, True]
