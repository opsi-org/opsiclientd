# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from __future__ import annotations

import json
from asyncio import AbstractEventLoop, BaseTransport, Protocol, Server, Transport, get_event_loop, run, sleep
from asyncio.exceptions import CancelledError
from dataclasses import asdict, dataclass, field
from threading import Event, Lock, Thread
from typing import Any

from OPSI.Util.Message import ChoiceSubject, Subject, SubjectsObserver  # type: ignore[import]
from opsicommon.logging import get_logger, log_context

logger = get_logger()


@dataclass
class NotificationRPC:
	method: str
	params: list[Any] = field(default_factory=list)
	id: str | int | None = None

	@staticmethod
	def from_json(json_str: str) -> NotificationRPC:
		return NotificationRPC(**json.loads(json_str))

	def to_json(self) -> str:
		return json.dumps(asdict(self))


class NotificationServerClientConnection(Protocol):
	def __init__(self, notification_server: NotificationServer) -> None:
		super().__init__()
		self._notification_server = notification_server
		self._buffer = bytearray()
		self._peer: tuple[str, int] = ("", 0)
		self._transport: Transport
		self._closed = Event()

	def __str__(self) -> str:
		return f"{self.__class__.__name__}({self._peer[0]}:{self._peer[1]})"

	__repr__ = __str__

	@property
	def subjects(self) -> list[Subject]:
		return self._notification_server._subjects

	def connection_made(self, transport: BaseTransport) -> None:
		self._peer = transport.get_extra_info("peername")
		logger.info("%s - connection made", self)
		assert isinstance(transport, Transport)
		self._transport = transport
		self._notification_server.client_connected(self)

	def connection_lost(self, exc: Exception | None = None) -> None:
		logger.info("%s - connection lost", self)
		self._notification_server.client_disconnected(self)
		self._closed.set()

	def data_received(self, data: bytes) -> None:
		logger.trace("%s - data received:", self, data)
		self._buffer += data
		rpcs = []
		while b"\r\n" in self._buffer or b"\1e" in self._buffer:  # multiple rpc calls separated by \r\n or \1e
			if b"\r\n" in self._buffer:
				rpc_data, self._buffer = self._buffer.split(b"\r\n", maxsplit=1)
			else:  # b"\1e" in byte_buffer
				rpc_data, self._buffer = self._buffer.split(b"\1e", maxsplit=1)
			logger.trace("Received RPC data: %r", rpc_data)
			try:
				rpc = NotificationRPC.from_json(rpc_data.decode("utf-8"))
				logger.debug("Received RPC: %r", rpc)
				rpcs.append(rpc)
			except Exception as err:
				logger.error("Invalid RPC data %r: %s", rpc_data, err, exc_info=True)
				continue
		for rpc in rpcs:
			self.process_rpc(rpc)

	def eof_received(self) -> bool:
		logger.debug("%s - EOF received", self)
		return False

	def __process_rpc(self, rpc: NotificationRPC) -> None:
		if rpc.method == "setSelectedIndexes":
			subject_id = rpc.params[0]
			selectedIndexes = rpc.params[1]
			for subject in self.subjects:
				if not isinstance(subject, ChoiceSubject) or subject.getId() != subject_id:
					continue
				subject.setSelectedIndexes(selectedIndexes)
				break

		elif rpc.method == "selectChoice":
			logger.debug("selectChoice(%s)", str(rpc.params)[1:-1])
			subject_id = rpc.params[0]
			for subject in self.subjects:
				if not isinstance(subject, ChoiceSubject) or subject.getId() != subject_id:
					continue
				subject.selectChoice()
				break
		else:
			raise ValueError(f"Invalid method '{rpc.method}'")

	def _process_rpc(self, rpc: NotificationRPC) -> None:
		try:
			self.__process_rpc(rpc)
		except Exception as err:
			logger.error("Error processing RPC %r: %s", rpc, err, exc_info=True)

	def process_rpc(self, rpc: NotificationRPC) -> None:
		Thread(target=self._process_rpc, args=[rpc], daemon=True).start()

	def send_rpc(self, rpc: NotificationRPC) -> None:
		self._transport.write(rpc.to_json().encode("utf-8") + b"\r\n")

	def close_connection(self) -> None:
		self._transport.close()

	def wait_closed(self, timeout: float = 5.0) -> bool:
		return self._closed.wait(timeout=timeout)


class NotificationServer(SubjectsObserver, Thread):
	def __init__(self, address: list[str] | str, start_port: int, subjects: list[Subject], notifier_id: str | None = None) -> None:
		Thread.__init__(self, daemon=True)
		SubjectsObserver.__init__(self)
		self._address = address
		self._start_port = start_port
		self.notifier_id = notifier_id
		self._server: Server | None = None
		self._server_lock = Lock()
		self._port = 0
		self._ready = Event()
		self._should_stop = False
		self._stopped = Event()
		self._error: Exception | None = None
		self._clients: list[NotificationServerClientConnection] = []
		self.setSubjects(subjects)

	@property
	def port(self) -> int:
		if self._port <= 0:
			raise RuntimeError("Server not started")
		return self._port

	def wait_ready(self, timeout: float | None = None) -> None:
		if not self._ready.wait(timeout=timeout):
			raise TimeoutError("Timeout waiting for notification server to start")
		if self._error:
			raise self._error

	def start_and_wait(self, timeout: float | None = None) -> None:
		with self._server_lock:
			self.start()
			self.wait_ready(timeout=timeout)

	def client_connected(self, client: NotificationServerClientConnection) -> None:
		if client not in self._clients:
			self._clients.append(client)
			self.subjectsChanged(self.getSubjects(), clients=[client])

	def client_disconnected(self, client: NotificationServerClientConnection) -> None:
		if client in self._clients:
			self._clients.remove(client)

	def messageChanged(self, subject: Subject, message: str) -> None:
		if subject not in self.getSubjects():
			logger.info("Unknown subject %s passed to messageChanged, automatically adding subject", subject)
			self.addSubject(subject)
		logger.debug("messageChanged: subject id '%s', message '%s'", subject.getId(), message)
		self.notify(name="messageChanged", params=[subject.serializable(), message])

	def selectedIndexesChanged(self, subject: Subject, selectedIndexes: list[int]) -> None:
		if subject not in self.getSubjects():
			logger.info("Unknown subject %s passed to selectedIndexesChanged, automatically adding subject", subject)
			self.addSubject(subject)
		logger.debug("selectedIndexesChanged: subject id '%s', selectedIndexes %s", subject.getId(), selectedIndexes)
		self.notify(name="selectedIndexesChanged", params=[subject.serializable(), selectedIndexes])

	def choicesChanged(self, subject: Subject, choices: list[str]) -> None:
		if subject not in self.getSubjects():
			logger.info("Unknown subject %s passed to choicesChanged, automatically adding subject", subject)
			self.addSubject(subject)
		logger.debug("choicesChanged: subject id '%s', choices %s", subject.getId(), choices)
		self.notify(name="choicesChanged", params=[subject.serializable(), choices])

	def progressChanged(self, subject: Subject, state: int, percent: float, timeSpend: float, timeLeft: float, speed: float) -> None:
		if subject not in self.getSubjects():
			logger.info("Unknown subject %s passed to progressChanged, automatically adding subject", subject)
			self.addSubject(subject)
		logger.debug(
			"progressChanged: subject id '%s', state %s, percent %s, timeSpend %s, timeLeft %s, speed %s",
			subject.getId(),
			state,
			percent,
			timeSpend,
			timeLeft,
			speed,
		)
		self.notify(name="progressChanged", params=[subject.serializable(), state, percent, timeSpend, timeLeft, speed])

	def endChanged(self, subject: Subject, end: int) -> None:
		if subject not in self.getSubjects():
			logger.info("Unknown subject %s passed to endChanged, automatically adding subject", subject)
			self.addSubject(subject)
		logger.debug("endChanged: subject id '%s', end %s", subject.getId(), end)
		self.notify(name="endChanged", params=[subject.serializable(), end])

	def subjectsChanged(self, subjects: list[Subject], clients: list[NotificationServerClientConnection] | None = None) -> None:
		logger.debug("subjectsChanged: subjects %s", subjects)
		param = [subject.serializable() for subject in subjects]
		self.notify(name="subjectsChanged", params=[param], clients=clients)

	def requestEndConnections(self) -> None:
		self.notify(name="endConnection", params=[])
		for client in self._clients:
			client.close_connection()
		for client in self._clients:
			client.wait_closed(timeout=5.0)

	def notify(self, name: str, params: list[Any], clients: list[NotificationServerClientConnection] | None = None) -> None:
		if not isinstance(params, list):
			params = [params]

		clients = clients or self._clients
		logger.debug("Sending notification %r %r to %d client(s)", name, params, len(clients))
		if not clients:
			return

		# json-rpc: notifications have id null
		rpc = NotificationRPC(method=name, params=params)
		for client in clients:
			try:
				logger.debug("Sending rpc %r to client %r", rpc, client)
				client.send_rpc(rpc)
			except Exception as err:
				logger.warning("Failed to send rpc client %r: %s", client, err)

	def _handle_asyncio_exception(self, loop: AbstractEventLoop, context: dict) -> None:
		logger.error(
			"Unhandled asyncio exception in %s (should_stop=%s) '%s': %s",
			self,
			self._should_stop,
			context.get("message"),
			exc_info=context.get("exception"),
		)

	async def _async_main(self) -> None:
		loop = get_event_loop()
		loop.set_exception_handler(self._handle_asyncio_exception)
		port = self._start_port
		for _ in range(10):
			try:
				self._server = await loop.create_server(lambda: NotificationServerClientConnection(self), self._address, port)
				self._port = port
				self._error = None
				break
			except Exception as err:
				self._error = err
				if isinstance(err, OSError) and err.errno in (48, 98, 10048):
					# MacOS [Errno 48] Address already in use
					# Linux [Errno 98] Address already in use
					# Windows [Errno 10048] only one usage of each socket address
					logger.debug(err)
					port += 1
					continue
				break

		self._ready.set()
		if self._error:
			logger.error(self._error, exc_info=True)
			return

		assert self._server
		addrs = ", ".join(str(sock.getsockname()) for sock in self._server.sockets)
		logger.info(f"Notification server serving on {addrs}")
		get_event_loop().create_task(self._server.serve_forever())

		while not self._should_stop:
			await sleep(1)

		if self._server:
			if self._clients:
				self.requestEndConnections()
			try:
				logger.debug("Closing notification server")
				self._server.close()
			except Exception as err:
				logger.debug(err)

	def run(self) -> None:
		with log_context({"instance": "notification server"}):
			try:
				logger.debug("Starting notification server")
				self._should_stop = False
				self._stopped.clear()
				run(self._async_main())
				self._ready.clear()
				logger.debug("Notification server stopped")
				self._stopped.set()
			except Exception as err:
				logger.error("Notification server error: %s", err, exc_info=True)

	def stop(self) -> None:
		self._should_stop = True
		with self._server_lock:
			logger.debug("Waiting for NotificationServer thread to stop")
			if not self._stopped.wait(5):
				logger.warning("Timed out waiting NotificationServer to stop")
