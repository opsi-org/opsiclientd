# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2018 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Pipes for remote procedure calls.

The classes are used to create named pipes for remote procedure calls.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import threading
import time
import socket
from ctypes import byref, c_char_p, c_ulong, create_string_buffer

from OPSI.Backend.Backend import describeInterface
import opsicommon.logging
from opsicommon.logging import logger
from OPSI.Types import forceUnicode
from OPSI.Util import fromJson, toJson
from OPSI.Service.JsonRpc import JsonRpc

if os.name == 'nt':
	from ctypes import windll


def ControlPipeFactory(opsiclientd):
	if os.name == 'posix':
		return PosixControlDomainSocket(opsiclientd)
	elif os.name == 'nt':
		return NTControlPipe(opsiclientd)
	else:
		raise NotImplementedError(f"Unsupported operating system: {os.name}")


class ClientConnection(threading.Thread):
	def __init__(self, controller, connection):
		threading.Thread.__init__(self)
		self._controller = controller
		self._connection = connection
		self._readTimeout = 1
		self._writeTimeout = 1
		self._clientInfo = []
		self._shouldStop = False
		logger.info(
			"%s created controller=%s connection=%s",
			self.__class__.__name__, self._controller, self._connection
		)
	
	def run(self):
		with opsicommon.logging.log_context({'instance' : 'control pipe connection'}):
			#while self._clientConnected and not self._stopEvent.is_set():
			#with self._comLock:
			try:
				while not self._shouldStop:
					request = self.read()
					if request:
						logger.info("Received request '%s'", request)
						response = self._controller.processIncomingRpc(request)
						logger.info("Sending response '%s'", response)
						self.write(response)
					time.sleep(0.5)
			except Exception as e:
				logger.error(e, exc_info=True)
			finally:
				self.clientDisconnected()
	
	def read(self):
		return ""

	def write(self, data):
		return False
	
	def clientDisconnected(self):
		self._shouldStop = True
		self._controller.clientDisconnected(self)


class ControlPipe(threading.Thread):
	"""
	Base class for a named pipe which handles remote procedure calls.
	"""
	connection_class = ClientConnection

	def __init__(self, opsiclientd):
		threading.Thread.__init__(self)
		self._opsiclientd = opsiclientd 
		self._opsiclientdRpcInterface = OpsiclientdRpcPipeInterface(self._opsiclientd)
		self._bufferSize = 4096
		self._running = False
		self._stopEvent = threading.Event()
		self._stopEvent.clear()
		self._clients = []
		self._comLock = threading.Lock()

	def run(self):
		with opsicommon.logging.log_context({'instance' : 'control pipe'}):
			self._running = True
			while not self._stopEvent.is_set():
				try:
					self.createPipe()
					client = self.waitForClient()
					logger.info("connection_class: %s", self.connection_class)
					connection = self.connection_class(self, client)
					self._clients.append(connection)
					connection.start()
				except Exception as e:
					logger.error(e, exc_info=True)
			self._running = False
	
	def stop(self):
		logger.debug("Stopping %s", self)
		self._stopEvent.set()
	
	def createPipe(self):
		pass
	
	def removePipe(self):
		pass
	
	def waitForClient(self):
		pass
	
	def clientDisconnected(self, client):
		if client in self._clients:
			logger.info("Client %s disconnected", client)
			self._clients.remove(client)
	
	def isRunning(self):
		return self._running

	def executeRpc(self, method, *params):
		#if not self._clientConnected:
		#	raise RuntimeError("Cannot execute rpc, no client connected")
		"""
		if not self._clientInfo:
			raise RuntimeError("Cannot execute rpc, not supported by client")
		with self._comLock:
			request = toJson({
				"id": 1,
				"method": method,
				"params": params
			})
			logger.info("Sending request '%s'", request)
			self.writePipe(request)
			response = self.readPipe()
			if response:
				logger.info("Received response '%s'", response)
				return fromJson(response)
		"""
	
	def processIncomingRpc(self, rpc):
		try:
			rpc = fromJson(rpc)
			jsonrpc = JsonRpc(
				instance=self._opsiclientdRpcInterface,
				interface=self._opsiclientdRpcInterface.getInterface(),
				rpc=rpc
			)
			jsonrpc.execute()
			"""
			if rpc.get("method") == "registerClient":
				self._clientInfo = rpc.get("params", [])
				threading.Timer(1.0,
					self.executeRpc,
					args=['blockLogin', self._opsiclientd._blockLogin]
				).start()
			"""
			return toJson(jsonrpc.getResponse())
		except Exception as rpcError:
			logger.error(rpcError, exc_info=True)
			return toJson({
				"id": None,
				"error": str(rpcError)
			})


class PosixClientConnection(ClientConnection):
	def read(self):
		logger.trace("Reading from connection %s", self._connection)
		self._connection.settimeout(self._readTimeout)
		try:
			data = self._connection.recv(4096)
			if not data:
				self.clientDisconnected()
			return data.decode("utf-8")
		except Exception as err:
			logger.trace("Failed to read from socket: %s", err)
	
	def write(self, data):
		if not data or not self._connection:
			return
		logger.trace("Writing to connection %s", self._connection)
		if not isinstance(data, bytes):
			data = data.encode("utf-8")
		self._connection.settimeout(self._writeTimeout)
		try:
			self._connection.sendall(data)
		except Exception as err:
			raise RuntimeError(f"Failed to write to socket: {err}")

class PosixControlDomainSocket(ControlPipe):
	"""
	PosixControlDomainSocket implements a control socket for posix operating systems
	"""
	connection_class = PosixClientConnection
	
	def __init__(self, opsiclientd):
		ControlPipe.__init__(self, opsiclientd)
		self._socketName = "/var/run/opsiclientd/socket"
		self._socket = None
		
	def createPipe(self):
		logger.trace("Creating socket %s", self._socketName)
		self.removePipe()
		self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
		self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
		self._socket.bind(self._socketName)
		self._socket.listen(1)
		logger.trace("Socket %s created", self._socketName)

	def removePipe(self):
		if self._socket:
			try:
				self._socket.close()
			except Exception as err:
				pass
		if os.path.exists(self._socketName):
			os.remove(self._socketName)
	
	def waitForClient(self):
		logger.info("Waiting for client to connected to %s", self._socketName)
		self._socket.settimeout(2.0)
		while True:
			try:
				connection, client_address = self._socket.accept()
				logger.notice("Client %s connected to %s", client_address, self._socketName)
				return connection
			except socket.timeout as err:
				if self._stopEvent.is_set():
					return
	

class NTPipeClientConnection(ClientConnection):
	def readPipe(self):
		logger.notice("Reading from pipe")
		chBuf = create_string_buffer(self._controller._bufferSize)
		cbRead = c_ulong(0)
		fReadSuccess = windll.kernel32.ReadFile(
			self._connection,
			chBuf,
			self._controller._bufferSize,
			byref(cbRead),
			None
		)
		logger.trace("Read %d bytes from pipe", cbRead.value)
		if fReadSuccess == 1 or cbRead.value != 0:
			return chBuf.value.decode()
		logger.trace("Failed to read from pipe")
	
	def writePipe(self, data):
		if not data:
			return
		logger.notice("Writing to pipe")
		if not isinstance(data, bytes):
			data = data.encode("utf-8")
		data += b"\0"

		cbWritten = c_ulong(0)
		fWriteSuccess = windll.kernel32.WriteFile(
			self._connection,
			c_char_p(data),
			len(data),
			byref(cbWritten),
			None
		)
		windll.kernel32.FlushFileBuffers(self._connection)
		#logger.trace("Wrote %d bytes to pipe", cbWritten.value)
		logger.notice("Wrote %d bytes to pipe", cbWritten.value)
		if not fWriteSuccess:
			raise RuntimeError("Failed to write to pipe")
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
	
	def createPipe(self):
		logger.info("Creating pipe %s", self._pipeName)
		self.removePipe()
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
			self._bufferSize,
			self._bufferSize,
			NMPWAIT_USE_DEFAULT_WAIT,
			None
		)
		if self._pipe == INVALID_HANDLE_VALUE:
			raise Exception(f"Failed to create named pipe: {windll.kernel32.GetLastError()}")

		logger.debug("Pipe %s created", self._pipeName)

	def removePipe(self):
		if self._pipe:
			try:
				windll.kernel32.FlushFileBuffers(self._pipe)
				windll.kernel32.DisconnectNamedPipe(self._pipe)
				windll.kernel32.CloseHandle(self._pipe)
			except Exception as e:
				pass
	
	def waitForClient(self):
		logger.info("Waiting for client to connected to %s", self._pipeName)
		# This call is blocking until a client connects
		fConnected = windll.kernel32.ConnectNamedPipe(self._pipe, None)
		if fConnected == 0 and windll.kernel32.GetLastError() == 535:
			# ERROR_PIPE_CONNECTED
			fConnected = 1

		if fConnected == 1:
			logger.notice("Client connected to %s", self._pipeName)
			return self._pipe
		
		windll.kernel32.CloseHandle(self._pipe)
		raise RuntimeError("Failed to connect to pipe")


class OpsiclientdRpcPipeInterface(object):
	def __init__(self, opsiclientd):
		self.opsiclientd = opsiclientd

	def getInterface(self):
		"""
		Returns what public methods are available and the signatures they use.

		These methods are represented as a dict with the following keys: \
		*name*, *params*, *args*, *varargs*, *keywords*, *defaults*.

		:returntype: [{},]
		"""
		return describeInterface(self)

	def getPossibleMethods_listOfHashes(self):
		return self.getInterface()

	def backend_getInterface(self):
		return self.getInterface()

	def backend_info(self):
		return {}

	def exit(self):
		return

	def backend_exit(self):
		return

	def getBlockLogin(self):
		logger.notice("rpc getBlockLogin: blockLogin is %s", self.opsiclientd._blockLogin)
		return self.opsiclientd._blockLogin

	def isRebootRequested(self):
		return self.isRebootTriggered()

	def isShutdownRequested(self):
		return self.isShutdownTriggered()

	def isRebootTriggered(self):
		return self.opsiclientd.isRebootTriggered()

	def isShutdownTriggered(self):
		return self.opsiclientd.isShutdownTriggered()
	
	def registerClient(self, name, version):
		return f"client {name}/{version} registered"
