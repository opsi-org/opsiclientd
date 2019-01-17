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
from ctypes import byref, c_char_p, c_ulong, create_string_buffer

from OPSI.Backend.Backend import describeInterface
from OPSI.Logger import Logger
from OPSI.Types import forceUnicode
from OPSI.Util import fromJson, toJson
from OPSI.Service.JsonRpc import JsonRpc

from ocdlib.Config import getLogFormat

if os.name == 'nt':
	from ctypes import windll

logger = Logger()


def ControlPipeFactory(opsiclientdRpcInterface):
	if os.name == 'posix':
		return PosixControlPipe(opsiclientdRpcInterface)
	elif os.name == 'nt':
		return NTControlPipe(opsiclientdRpcInterface)
	else:
		raise NotImplementedError(u"Unsupported operating system %s" % os.name)


class ControlPipe(threading.Thread):
	"""
	Base class for a named pipe which handles remote procedure calls.
	"""
	def __init__(self, opsiclientdRpcInterface):
		logger.setLogFormat(getLogFormat(u'control pipe'), object=self)
		threading.Thread.__init__(self)
		self._opsiclientdRpcInterface = opsiclientdRpcInterface
		self._pipe = None
		self._pipeName = ""
		self._bufferSize = 4096
		self._running = False
		self._stopped = False

	def stop(self):
		self._stopped = True

	def closePipe(self):
		return

	def isRunning(self):
		return self._running

	def executeRpc(self, rpc):
		try:
			rpc = fromJson(rpc)
			jsonrpc = JsonRpc(
				instance=self._opsiclientdRpcInterface,
				interface=self._opsiclientdRpcInterface.getInterface(),
				rpc=rpc
			)
			jsonrpc.execute()
			return toJson(jsonrpc.getResponse())
		except Exception as rpcError:
			logger.logException(rpcError)


class PosixControlPipe(ControlPipe):
	"""
	Control pipe for posix operating systems
	"""

	def __init__(self, opsiclientdRpcInterface):
		ControlPipe.__init__(self, opsiclientdRpcInterface)
		self._pipeName = "/var/run/opsiclientd/fifo"

	def createPipe(self):
		logger.debug2(u"Creating pipe {}", self._pipeName)
		if not os.path.exists(os.path.dirname(self._pipeName)):
			os.mkdir(os.path.dirname(self._pipeName))

		if os.path.exists(self._pipeName):
			os.unlink(self._pipeName)

		os.mkfifo(self._pipeName)
		logger.debug2(u"Pipe {} created", self._pipeName)

	def closePipe(self):
		if self._pipe:
			try:
				os.close(self._pipe)
			except Exception:
				pass

	def run(self):
		self._running = True
		try:
			self.createPipe()
			while self._running:
				try:
					logger.debug2(u"Opening named pipe {}", self._pipeName)
					self._pipe = os.open(self._pipeName, os.O_RDONLY)
					logger.debug2(u"Reading from pipe {}", self._pipeName)
					rpc = os.read(self._pipe, self._bufferSize)
					os.close(self._pipe)
					if not rpc:
						logger.error(u"No rpc from pipe")
						continue
					logger.debug2(u"Received rpc from pipe: {!r}", rpc)
					result = self.executeRpc(rpc)
					logger.debug2(u"Opening named pipe {}", self._pipeName)
					timeout = 3
					ta = 0.0
					while ta < timeout:
						try:
							self._pipe = os.open(self._pipeName, os.O_WRONLY | os.O_NONBLOCK)
							break
						except Exception as e:
							if not hasattr(e, 'errno') or (e.errno != 6):
								raise

							time.sleep(0.01)
							ta += 0.01

					if ta >= timeout:
						logger.error(u"Failed to write to pipe (timed out after {:d} seconds)", timeout)
						continue

					logger.debug2(u"Writing to pipe")
					written = os.write(self._pipe, result)
					logger.debug2(u"Number of bytes written: %d" % written)
					if len(result) != written:
						logger.error("Failed to write all bytes to pipe ({:d}/{:d})", written, len(result))

				except Exception as e:
					logger.error(u"Pipe IO error: {}", forceUnicode(e))
				finally:
					try:
						os.close(self._pipe)
					except Exception:
						pass
		except Exception as e:
			logger.logException(e)

		logger.notice(u"ControlPipe exiting")
		if os.path.exists(self._pipeName):
			os.unlink(self._pipeName)
		self._running = False


class NTControlPipeConnection(threading.Thread):

	def __init__(self, ntControlPipe, pipe, bufferSize):
		logger.setLogFormat(getLogFormat(u'control pipe'), object=self)
		threading.Thread.__init__(self)
		self._ntControlPipe = ntControlPipe
		self._pipe = pipe
		self._bufferSize = bufferSize
		logger.debug(u"NTControlPipeConnection initiated")

	def closePipe(self):
		if self._pipe:
			try:
				windll.kernel32.CloseHandle(self._pipe)
			except Exception:
				pass

	def run(self):
		self._running = True
		try:
			chBuf = create_string_buffer(self._bufferSize)
			cbRead = c_ulong(0)
			while self._running:
				logger.debug2(u"Reading fom pipe")
				fReadSuccess = windll.kernel32.ReadFile(self._pipe, chBuf, self._bufferSize, byref(cbRead), None)
				if fReadSuccess == 1 or cbRead.value != 0:
					logger.debug(u"Received rpc from pipe {!r}", chBuf.value)
					result = "%s\0" % self._ntControlPipe.executeRpc(chBuf.value)
					cbWritten = c_ulong(0)
					logger.debug2(u"Writing to pipe")
					fWriteSuccess = windll.kernel32.WriteFile(
						self._pipe,
						c_char_p(result),
						len(result),
						byref(cbWritten),
						None
					)
					logger.debug2(u"Number of bytes written: {:d}", cbWritten.value)
					if not fWriteSuccess:
						logger.error(u"Could not reply to the client's request from the pipe")
						break

					if len(result) != cbWritten.value:
						logger.error(u"Failed to write all bytes to pipe ({:d}/{:d})", cbWritten.value, len(result))
						break

					break
				else:
					logger.error(u"Failed to read from pipe")
					break

			windll.kernel32.FlushFileBuffers(self._pipe)
			windll.kernel32.DisconnectNamedPipe(self._pipe)
			windll.kernel32.CloseHandle(self._pipe)
		except Exception as e:
			logger.error(u"NTControlPipeConnection error: {}", forceUnicode(e))

		logger.debug(u"NTControlPipeConnection exiting")
		self._running = False


class NTControlPipe(ControlPipe):
	"""
	Control pipe for windows operating systems.
	"""

	def __init__(self, opsiclientdRpcInterface):
		threading.Thread.__init__(self)
		ControlPipe.__init__(self, opsiclientdRpcInterface)
		self._pipeName = "\\\\.\\pipe\\opsiclientd"

	def createPipe(self):
		logger.info(u"Creating pipe {}", self._pipeName)
		PIPE_ACCESS_DUPLEX = 0x3
		PIPE_TYPE_MESSAGE = 0x4
		PIPE_READMODE_MESSAGE = 0x2
		PIPE_WAIT = 0
		PIPE_UNLIMITED_INSTANCES = 255
		NMPWAIT_USE_DEFAULT_WAIT = 0
		INVALID_HANDLE_VALUE = -1
		self._pipe = windll.kernel32.CreateNamedPipeA(
			self._pipeName,
			PIPE_ACCESS_DUPLEX,
			PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
			PIPE_UNLIMITED_INSTANCES,
			self._bufferSize,
			self._bufferSize,
			NMPWAIT_USE_DEFAULT_WAIT,
			None
		)
		if self._pipe == INVALID_HANDLE_VALUE:
			raise Exception(u"Failed to create named pipe")

		logger.debug(u"Pipe {} created", self._pipeName)

	def run(self):
		ERROR_PIPE_CONNECTED = 535
		self._running = True
		try:
			while self._running:
				self.createPipe()
				logger.debug(u"Connecting to named pipe {}", self._pipeName)
				# This call is blocking until a client connects
				fConnected = windll.kernel32.ConnectNamedPipe(self._pipe, None)
				if fConnected == 0 and windll.kernel32.GetLastError() == ERROR_PIPE_CONNECTED:
					fConnected = 1

				if fConnected == 1:
					logger.debug(u"Connected to named pipe {}", self._pipeName)
					logger.debug(u"Creating NTControlPipeConnection")
					cpc = NTControlPipeConnection(self, self._pipe, self._bufferSize)
					cpc.start()
					logger.debug(u"NTControlPipeConnection thread started")
				else:
					logger.error(u"Failed to connect to pipe")
					windll.kernel32.CloseHandle(self._pipe)
		except Exception as e:
			logger.logException(e)

		logger.notice(u"ControlPipe exiting")
		self._running = False


class OpsiclientdRpcPipeInterface(object):
	def __init__(self, opsiclientd):
		self.opsiclientd = opsiclientd
		logger.setLogFormat(getLogFormat(u'opsiclientd'), object=self)

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
		logger.notice(u"rpc getBlockLogin: blockLogin is {}", self.opsiclientd._blockLogin)
		return self.opsiclientd._blockLogin

	def isRebootRequested(self):
		return self.isRebootTriggered()

	def isShutdownRequested(self):
		return self.isShutdownTriggered()

	def isRebootTriggered(self):
		return self.opsiclientd.isRebootTriggered()

	def isShutdownTriggered(self):
		return self.opsiclientd.isShutdownTriggered()
