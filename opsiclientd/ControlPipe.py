# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Pipes for remote procedure calls.

The classes are used to create named pipes for remote procedure calls.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from ctypes import byref, c_char_p, c_ulong, create_string_buffer
from datetime import datetime

from OPSI.Service.JsonRpc import JsonRpc  # type: ignore[import]
from OPSI.Util import fromJson, toJson  # type: ignore[import]
from opsicommon.logging import get_logger, log_context

from opsiclientd.webserver.rpc.control import get_pipe_control_interface

if os.name == "nt":
	from ctypes import windll  # type: ignore[attr-defined]
else:
	windll = None

logger = get_logger("opsiclientd")


def ControlPipeFactory(opsiclientd):
	if os.name == "posix":
		return PosixControlDomainSocket(opsiclientd)
	if os.name == "nt":
		return NTControlPipe(opsiclientd)
	raise NotImplementedError(f"Unsupported operating system: {os.name}")


class ClientConnection(threading.Thread):
	def __init__(self, controller: ControlPipe, connection, client_id: str) -> None:
		threading.Thread.__init__(self, name="ControlPipe-ClientConnection")
		self._controller = controller
		self._connection = connection
		self.client_id = client_id
		self._readTimeout = 1
		self._writeTimeout = 1
		self._encoding = "utf-8"
		self.clientInfo: list[str] = []
		self.comLock = threading.Lock()
		self._stopEvent = threading.Event()
		self._stopEvent.clear()
		self.login_capable = False
		self.login_user_executed: datetime | None = None
		logger.trace("%s created controller=%s connection=%s", self.__class__.__name__, self._controller, self._connection)

	def __str__(self):
		return f"<{self.__class__.__name__} {self.client_id}>"

	def run(self):
		with log_context({"instance": "control pipe"}):
			try:
				while not self._stopEvent.is_set():
					if self.clientInfo:
						self.checkConnection()
					else:
						# Old protocol
						with self.comLock:
							request = self.read()
							if request:
								logger.info("Received request '%s' from %s", request, self)
								response = self.processIncomingRpc(request)
								logger.info("Sending response '%s' to %s", response, self)
								self.write(response)

								if self.clientInfo:
									# Switch to new protocol
									self.executeRpc(
										"blockLogin",
										[self._controller._opsiclientd._blockLogin],
										with_lock=False,
									)
					time.sleep(0.5)
			except Exception as err:
				logger.error(err, exc_info=True)
			finally:
				self.clientDisconnected()

	def stop(self):
		self._stopEvent.set()

	def read(self):
		return ""

	def write(self, data):
		return False

	def checkConnection(self):
		pass

	def clientDisconnected(self):
		self.stop()
		self._controller.clientDisconnected(self)

	def processIncomingRpc(self, rpc):
		try:
			rpc = fromJson(rpc)
			if rpc.get("method") == "registerClient":
				# New client protocol
				self.clientInfo = rpc.get("params", [])
				self.login_capable = True
				logger.info("Client %s info set to: %s", self, self.clientInfo)
				return toJson(
					{"id": rpc.get("id"), "result": f"client {'/'.join(self.clientInfo)}/{self.client_id} registered", "error": None}
				)
			jsonrpc = JsonRpc(
				instance=self._controller._opsiclientdRpcInterface,
				interface=self._controller._opsiclientdRpcInterface.backend_getInterface(),
				rpc=rpc,
			)
			jsonrpc.execute()
			return toJson(jsonrpc.getResponse())
		except Exception as rpc_error:
			logger.error(rpc_error, exc_info=True)
			return toJson({"id": None, "error": str(rpc_error)})

	def executeRpc(self, method, params=None, with_lock=True):
		params = params or []
		with log_context({"instance": "control pipe"}):
			rpc_id = 1
			if not self.clientInfo:
				return {"id": rpc_id, "error": f"Cannot execute rpc, not supported by client {self}", "result": None}

			request = {"id": rpc_id, "method": method, "params": params}
			try:
				if with_lock:
					self.comLock.acquire()
				try:
					request_json = toJson(request)
					logger.info("Sending request '%s' to client %s", request_json, self)
					self.write(request_json)
					response_json = self.read()
					if not response_json:
						logger.warning("No response for method '%s' received from client %s", request["method"], self)
						return {"id": rpc_id, "error": None, "result": None}
					logger.info("Received response '%s' from client %s", response_json, self)
					response = fromJson(response_json)
					if method == "loginUser" and response.get("result"):
						self.login_user_executed = datetime.now()
						# Credential provider can only handle one successful login.
						# Ensure, that the credential provider is not used for a
						# second login if it keeps the pipe connection open.
						self.login_capable = False
					return response
				finally:
					if with_lock:
						self.comLock.release()
			except Exception as client_err:
				logger.error(client_err, exc_info=True)
				return {"id": rpc_id, "error": str(client_err), "result": None}


class ControlPipe(threading.Thread):
	"""
	Base class for a named pipe which handles remote procedure calls.
	"""

	connection_class = ClientConnection

	def __init__(self, opsiclientd) -> None:
		threading.Thread.__init__(self, name="ControlPipe")
		self._opsiclientd = opsiclientd
		self._opsiclientdRpcInterface = get_pipe_control_interface(self._opsiclientd)
		self.bufferSize = 4096
		self._running = False
		self._stopEvent = threading.Event()
		self._stopEvent.clear()
		self._clients: list[ClientConnection] = []
		self._clientLock = threading.Lock()

	def run(self):
		with log_context({"instance": "control pipe"}):
			self._running = True
			self.setup()
			try:
				while not self._stopEvent.is_set():
					try:
						client, client_id = self.waitForClient()
						if self._stopEvent.is_set():
							break
						with self._clientLock:
							connection = self.connection_class(self, client, client_id)
							self._clients.append(connection)
							connection.daemon = True
							connection.start()
					except Exception as err1:
						logger.error(err1, exc_info=True)
						self.setup()
			except Exception as err2:
				logger.error(err2, exc_info=True)
			self._running = False
			self.teardown()

	def stop(self):
		logger.debug("Stopping %s", self)
		with self._clientLock:
			for client in self._clients:
				client.stop()
		self._stopEvent.set()

	def setup(self):
		pass

	def teardown(self):
		pass

	def waitForClient(self):
		return (None, None)

	def clientDisconnected(self, client):
		with self._clientLock:
			if client in self._clients:
				logger.info("Client %s disconnected", client)
				self._clients.remove(client)

	def isRunning(self):
		return self._running

	def getClientInfo(self):
		return [c.clientInfo for c in self._clients]

	def getLoginCapableCredentialProvider(self) -> ClientConnection:
		return_client = None
		for client in self._clients:
			logger.debug("Checking client: %r (login_user_executed=%r)", client.clientInfo, client.login_user_executed)
			if client.clientInfo and client.login_capable:
				# Use latest ClientConnection (do not return / break)
				return_client = client
		if not return_client:
			raise RuntimeError("Cannot execute rpc, no login capable opsi credential provider connected")
		return return_client

	def credentialProviderConnected(self, login_capable=None):
		for client in self._clients:
			logger.debug("Checking client: %r (login_user_executed=%r)", client.clientInfo, client.login_user_executed)
			if client.clientInfo and (login_capable is None or login_capable == client.login_capable):
				return True
		return False

	def executeRpc(self, method, *params):
		with log_context({"instance": "control pipe"}):
			if not self._clients:
				raise RuntimeError("Cannot execute rpc, no client connected")

			clients = self._clients
			if method == "loginUser":
				# Send loginUser to latest connected credential provider only
				self._clients = [self.getLoginCapableCredentialProvider()]

			responses = []
			errors = []
			for client in clients:
				if method == "loginUser" and not client.login_capable:
					continue
				response = client.executeRpc(method, params)
				responses.append(response)
				if response.get("error"):
					errors.append(response["error"])

			if len(errors) == len(responses):
				raise RuntimeError(", ".join(errors))

			return responses


class PosixClientConnection(ClientConnection):
	def checkConnection(self):
		# TODO
		pass

	def read(self):
		logger.trace("Reading from connection %s", self._connection)
		self._connection.settimeout(self._readTimeout)
		try:
			data = self._connection.recv(4096)
			if not data:
				self.clientDisconnected()
			return data.decode(self._encoding)
		except Exception as err:
			logger.trace("Failed to read from socket: %s", err)
		return None

	def write(self, data):
		if not data or not self._connection:
			return
		logger.trace("Writing to connection %s", self._connection)
		if not isinstance(data, bytes):
			data = data.encode(self._encoding)
		self._connection.settimeout(self._writeTimeout)
		try:
			self._connection.sendall(data)
		except Exception as err:
			raise RuntimeError(f"Failed to write to socket: {err}") from err


class PosixControlDomainSocket(ControlPipe):
	"""
	PosixControlDomainSocket implements a control socket for posix operating systems
	"""

	connection_class = PosixClientConnection

	def __init__(self, opsiclientd):
		ControlPipe.__init__(self, opsiclientd)
		self._socketName = "/var/run/opsiclientd/socket"
		self._socket = None

	def setup(self):
		logger.trace("Creating socket %s", self._socketName)
		self.teardown()
		self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self._socket.bind(self._socketName)
		self._socket.listen(1)
		logger.trace("Socket %s created", self._socketName)

	def teardown(self):
		if self._socket:
			try:
				self._socket.close()
			except socket.error:
				pass
		if os.path.exists(self._socketName):
			os.remove(self._socketName)

	def waitForClient(self):
		logger.debug("Waiting for client to connect to %s", self._socketName)
		self._socket.settimeout(2.0)
		while True:
			try:
				connection, client_address = self._socket.accept()
				logger.notice("Client %s connected to %s", client_address, self._socketName)
				return (connection, client_address)
			except socket.timeout:
				if self._stopEvent.is_set():
					return (None, None)


class NTPipeClientConnection(ClientConnection):
	def checkConnection(self):
		chBuf = create_string_buffer(self._controller.bufferSize)
		cbRead = c_ulong(0)
		cbAvailable = c_ulong(0)
		fSuccess = windll.kernel32.PeekNamedPipe(
			self._connection, chBuf, self._controller.bufferSize, byref(cbRead), byref(cbAvailable), None
		)
		if fSuccess != 1:
			error = windll.kernel32.GetLastError()
			if error == 109:  # ERROR_BROKEN_PIPE
				self.clientDisconnected()

	def read(self):
		data = b""
		while True:
			logger.trace("Reading from pipe")
			chBuf = create_string_buffer(self._controller.bufferSize)
			cbRead = c_ulong(0)
			fSuccess = windll.kernel32.ReadFile(self._connection, chBuf, self._controller.bufferSize, byref(cbRead), None)
			logger.trace("Read %d bytes from pipe", cbRead.value)
			if cbRead.value > 0:
				data += chBuf.value

			if fSuccess != 1:
				if windll.kernel32.GetLastError() == 234:  # ERROR_MORE_DATA
					continue
				if data:
					return data.decode()
				if windll.kernel32.GetLastError() == 109:  # ERROR_BROKEN_PIPE
					self.clientDisconnected()

			return data.decode()

	def write(self, data):
		if not data:
			return
		logger.trace("Writing to pipe")
		if not isinstance(data, bytes):
			data = data.encode(self._encoding)
		data += b"\0"

		cbWritten = c_ulong(0)
		fSuccess = windll.kernel32.WriteFile(self._connection, c_char_p(data), len(data), byref(cbWritten), None)
		windll.kernel32.FlushFileBuffers(self._connection)
		logger.trace("Wrote %d bytes to pipe", cbWritten.value)
		if not fSuccess:
			error = windll.kernel32.GetLastError()
			if error in (232, 109):  # ERROR_NO_DATA, ERROR_BROKEN_PIPE
				self.clientDisconnected()
				return
			raise RuntimeError(f"Failed to write to pipe (error: {error})")
		if len(data) != cbWritten.value:
			raise RuntimeError(
				f"Failed to write all bytes to pipe ({cbWritten.value}/{len(data)})",
			)


class NTControlPipe(ControlPipe):
	"""
	Control pipe for windows operating systems.
	"""

	connection_class = NTPipeClientConnection

	def __init__(self, opsiclientd):
		ControlPipe.__init__(self, opsiclientd)
		self._pipeName = "\\\\.\\pipe\\opsiclientd"
		self._pipe = None
		self._client_id = 0

	def setup(self):
		pass

	def teardown(self):
		if self._pipe:
			try:
				windll.kernel32.FlushFileBuffers(self._pipe)
				windll.kernel32.DisconnectNamedPipe(self._pipe)
				windll.kernel32.CloseHandle(self._pipe)
			except Exception:
				pass

	def waitForClient(self):
		logger.trace("Creating pipe %s", self._pipeName)
		PIPE_ACCESS_DUPLEX = 0x3
		PIPE_TYPE_MESSAGE = 0x4
		PIPE_READMODE_MESSAGE = 0x2
		PIPE_WAIT = 0
		PIPE_UNLIMITED_INSTANCES = 255
		NMPWAIT_USE_DEFAULT_WAIT = 0
		INVALID_HANDLE_VALUE = -1
		self._pipe = windll.kernel32.CreateNamedPipeA(
			self._pipeName.encode("ascii"),
			PIPE_ACCESS_DUPLEX,
			PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
			PIPE_UNLIMITED_INSTANCES,
			self.bufferSize,
			self.bufferSize,
			NMPWAIT_USE_DEFAULT_WAIT,
			None,
		)
		if self._pipe == INVALID_HANDLE_VALUE:
			raise RuntimeError(f"Failed to create named pipe: {windll.kernel32.GetLastError()}")

		logger.debug("Pipe %s created, waiting for client to connect", self._pipeName)
		# This call is blocking until a client connects
		fConnected = windll.kernel32.ConnectNamedPipe(self._pipe, None)
		if fConnected == 0 and windll.kernel32.GetLastError() == 535:
			# ERROR_PIPE_CONNECTED
			fConnected = 1

		if fConnected == 1:
			logger.notice("Client connected to %s", self._pipeName)
			self._client_id += 1
			return (self._pipe, f"#{self._client_id}")

		error = windll.kernel32.GetLastError()
		windll.kernel32.CloseHandle(self._pipe)
		raise RuntimeError(f"Failed to connect to pipe (error: {error})")
