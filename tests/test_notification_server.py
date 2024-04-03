# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
test_notification_server
"""

import socket
import time
from threading import Thread

from OPSI.Util.Message import ChoiceSubject  # type: ignore[import]

from opsiclientd.notification_server import NotificationRPC, NotificationServer


def test_start_stop_notification_server() -> None:
	address = "127.0.0.1"
	start_port = 44044
	choice_subject = ChoiceSubject(id="choice")
	choice_subject.setChoices(["abort", "start"])
	subjects = [choice_subject]
	notification_server1 = NotificationServer(address=address, start_port=start_port, subjects=subjects)
	notification_server1.start()
	notification_server1.wait_ready(5)
	assert notification_server1.port == start_port

	notification_server2 = NotificationServer(address=address, start_port=start_port, subjects=subjects)
	notification_server2.start()
	notification_server2.wait_ready(5)
	assert notification_server2.port == start_port + 1

	notification_server1.stop()
	notification_server2.stop()


class NotificationClient(Thread):
	def __init__(self, address: str, port: int) -> None:
		super().__init__(daemon=True)
		self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
		self.sock.connect((address, port))
		self.rpcs_received: list[NotificationRPC] = []
		self._buffer = bytearray()
		self.start()

	def run(self) -> None:
		while data := self.sock.recv(4096):
			self._buffer += data
			while b"\r\n" in self._buffer or b"\1e" in self._buffer:  # multiple rpc calls separated by \r\n or \1e
				if b"\r\n" in self._buffer:
					rpc_data, self._buffer = self._buffer.split(b"\r\n", maxsplit=1)
				else:  # b"\1e" in byte_buffer
					rpc_data, self._buffer = self._buffer.split(b"\1e", maxsplit=1)

				# print(f"Received rpc_data: {rpc_data!r}")
				try:
					rpc = NotificationRPC.from_json(rpc_data.decode("utf-8"))
				except Exception as err:
					print(f"Error decoding rpc_data {rpc_data!r}: {err}")
					continue
				# print(f"Received rpc: {rpc!r}")
				self.rpcs_received.append(rpc)
				if rpc.method == "endConnection":
					return

	def send_rpc(self, rpc: NotificationRPC) -> None:
		self.sock.sendall(rpc.to_json().encode("utf-8") + b"\r\n")

	def stop(self) -> None:
		self.sock.close()


def test_notification_server_multi_client() -> None:
	address = "127.0.0.1"
	start_port = 44044

	abort_called = False
	start_called = False

	def abort_callback(choice_subject: ChoiceSubject) -> None:
		nonlocal abort_called
		abort_called = True

	def start_callback(choice_subject: ChoiceSubject) -> None:
		nonlocal start_called
		start_called = True

	choice_subject = ChoiceSubject(id="choice", callbacks=[abort_callback, start_callback])
	choice_subject.setChoices(["abort", "start"])
	subjects = [choice_subject]
	notification_server = NotificationServer(address=address, start_port=start_port, subjects=subjects)
	notification_server.start()
	notification_server.wait_ready(5)
	assert notification_server.port == start_port

	client1 = NotificationClient(address, start_port)
	client2 = NotificationClient(address, start_port)
	time.sleep(1)

	client1.send_rpc(NotificationRPC(id=1, method="setSelectedIndexes", params=["choice", 0]))
	time.sleep(1)

	for client in [client1, client2]:
		print(client.rpcs_received)
		assert len(client.rpcs_received) == 2
		assert client.rpcs_received[0].method == "subjectsChanged"
		assert client.rpcs_received[1].method == "selectedIndexesChanged"
		assert len(client.rpcs_received[1].params) == 2
		assert client.rpcs_received[1].params[0] == choice_subject.serializable()
		assert client.rpcs_received[1].params[1] == [0]
		client.rpcs_received = []

	assert not abort_called
	assert not start_called

	client2.send_rpc(NotificationRPC(id=1, method="setSelectedIndexes", params=["choice", 1]))
	client2.send_rpc(NotificationRPC(id=1, method="selectChoice", params=["choice"]))
	time.sleep(1)

	for client in [client1, client2]:
		print(client.rpcs_received)
		assert len(client.rpcs_received) == 1
		assert client.rpcs_received[0].method == "selectedIndexesChanged"
		assert len(client.rpcs_received[0].params) == 2
		assert client.rpcs_received[0].params[0] == choice_subject.serializable()
		assert client.rpcs_received[0].params[1] == [1]

	assert not abort_called
	assert start_called

	notification_server.stop()

	for client in [client1, client2]:
		assert client.rpcs_received[-1].method == "endConnection"
		assert client.rpcs_received[-1].params == []
		assert not client.is_alive()
