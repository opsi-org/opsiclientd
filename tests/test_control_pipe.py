# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
test_control_pipe
"""

from __future__ import annotations

import socket
import threading
import time

import pytest

from opsiclientd.ControlPipe import ControlPipeFactory, PosixControlDomainSocket
from opsiclientd.Opsiclientd import Opsiclientd
from opsiclientd.webserver.rpc.jsonrpc import JSONRPCRequest, JSONRPCResponse, deserialize_data, jsonrpc_response_from_data, serialize_data
from opsicommon.system.info import is_windows
from .utils import default_config  # noqa


class PipeClient(threading.Thread):
	def __init__(self, socket_path: str) -> None:
		super().__init__(daemon=True)
		self.socket_path = socket_path
		self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self.data_received: list[bytes] = []
		self.response_data = b""

	def stop(self) -> None:
		self.socket.close()

	def run(self) -> None:
		self.socket.connect(self.socket_path)
		self.socket.settimeout(0.1)
		while True:
			try:
				data = self.socket.recv(4096)
			except socket.timeout:
				continue
			except OSError:
				break
			if not data:
				break
			self.data_received.append(data)
			if self.response_data:
				self.send(self.response_data)
				self.response_data = b""

	def send(self, data: bytes) -> None:
		self.socket.sendall(data)


@pytest.mark.linux
def test_control_pipe() -> None:  # noqa
	ocd = Opsiclientd()
	control_pipe = ControlPipeFactory(ocd)
	assert isinstance(control_pipe, PosixControlDomainSocket)
	control_pipe.start()
	pipe_client = PipeClient(control_pipe._socketName)
	time.sleep(1)
	try:
		pipe_client.start()
		request = JSONRPCRequest(id=1, method="registerClient", params=["opsi-login-blocker", "4.3.0.0"])
		pipe_client.send(serialize_data(request, "json"))
		time.sleep(2)
		print(pipe_client.data_received)
		assert len(pipe_client.data_received) == 2

		response = jsonrpc_response_from_data(pipe_client.data_received[0], "json")[0]
		assert isinstance(response, JSONRPCResponse)
		assert response.id == request.id
		con_id = "#1" if is_windows() else "unix_socket"
		assert response.result == f"client opsi-login-blocker/4.3.0.0/{con_id} registered"
		assert len(control_pipe._clients) == 1
		assert control_pipe._clients[0].clientInfo == ["opsi-login-blocker", "4.3.0.0"]

		request_dict = deserialize_data(pipe_client.data_received[1], "json")
		assert request_dict["id"] == 1
		assert request_dict["method"] == "blockLogin"
		assert request_dict["params"] == [True]

		request = JSONRPCRequest(id=1, method="registerClient", params=["opsi-login-blocker", "4.3.0.0"])
		pipe_client.send(serialize_data({"id": 1, "result": "blocking login", "error": None}, "json"))

		assert control_pipe._clients[0].login_capable

		method = "some_method"
		params = ["aßdöirkdksd", 2]
		pipe_client.response_data = serialize_data({"id": 1, "result": "some result", "error": None}, "json")
		response = control_pipe.executeRpc(method, *params)[0]

		print(response)
		print(pipe_client.data_received)

		assert isinstance(response, JSONRPCResponse)
		assert response.result == "some result"
		assert response.id == 1

		assert len(pipe_client.data_received) == 3
		request_dict = deserialize_data(pipe_client.data_received[2], "json")
		print(request)
		assert request_dict["id"] == 1
		assert request_dict["method"] == method
		assert request_dict["params"] == params

	finally:
		pipe_client.stop()
		control_pipe.stop()
