# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
Server component for controlling opsiclientd.

These classes are used to create a https service which executes remote
procedure calls
"""

# pylint: disable=too-many-lines

import codecs
import os
import re
import shutil
import sys
import threading
import time
import json
import urllib
import email
import tempfile
import platform
import datetime
from OpenSSL import crypto
import msgpack

from twisted.internet import reactor
from twisted.internet.error import CannotListenError
from twisted.web.static import File
from twisted.web.resource import Resource
from twisted.web import server
from autobahn.twisted.websocket import WebSocketServerFactory, WebSocketServerProtocol
from autobahn.twisted.resource import WebSocketResource

from OPSI import System
from OPSI.Util.Log import truncateLogData
from OPSI.Exceptions import OpsiAuthenticationError
from OPSI.Service import SSLContext, OpsiService
from OPSI.Service.Worker import WorkerOpsi, WorkerOpsiJsonRpc, WorkerOpsiJsonInterface
from OPSI.Service.Resource import ResourceOpsi, ResourceOpsiJsonRpc, ResourceOpsiJsonInterface
from OPSI.Types import forceBool, forceInt, forceUnicode

from opsicommon.logging import (
	logger, log_context, secret_filter,
	OPSI_LEVEL_TO_LEVEL, LEVEL_TO_NAME
)
from opsiclientd.ControlPipe import OpsiclientdRpcPipeInterface
from opsiclientd.Config import Config
from opsiclientd.Events.Utilities.Generators import getEventGenerator
from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.OpsiService import ServiceConnection
from opsiclientd.State import State
from opsiclientd.SoftwareOnDemand import ResourceKioskJsonRpc
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS
from opsiclientd.Timeline import Timeline

config = Config()
state = State()

INFO_PAGE = '''<!DOCTYPE html>
<html>
<head>
	<meta http-equiv="Content-Type" content="text/xhtml; charset=utf-8" />
	<title>%(hostname)s opsi client daemon info</title>
	<link rel="stylesheet" type="text/css" href="/opsiclientd.css" />
	%(head)s
	<script type="text/javascript">
	function onPageLoad(){
		onLoad();
		//var logDiv = document.getElementById("infopage-opsiclientd-log");
		//logDiv.scrollTop = logDiv.scrollHeight;
	}
	</script>
</head>
<body onload="onPageLoad();" onresize="onResize();">
	<p id="title">opsi client daemon info</p>
	<div id="infopage-timeline-box">
		<p id="infopage-timeline-title">Timeline</p>
		<div class="timeline-default" id="opsiclientd-timeline" style="height: 400px; border: 1px solid #aaaaaa"></div>
		<noscript>
		This page uses Javascript to show you a Timeline. Please enable Javascript in your browser to see the full page. Thank you.
		</noscript>
	</div>
</body>
</html>
'''

LOG_VIEWER_PAGE = '''<!DOCTYPE html>
<html>
<head>
	<title>opsiclientd - log viewer</title>
	<link rel="stylesheet" href="/opsiclientd.css" />
	<script src="/javascript/log_viewer.js"></script>
	<script src="/javascript/msgpack.js"></script>
	<script>
		function onLoad() {
			startLog(20000);
		}
	</script>
</head>
<body onload="onLoad();">
	<div id="log-settings">
		<div class="log-setting">
			<label for="log-level-filter">Filter by level:</label>
			<input id="log-level-filter" type="number" min="1" max="9" value="9" onchange="applyLevelFilter(this.value);">
		</div>
		<div class="log-setting">
			<label for="log-context-filter">Filter by context:</label>
			<input id="log-context-filter" type="text" onchange="applyContextFilter(this.value);"/>
		</div>
		<div class="log-setting">
			<label for="log-message-filter">Filter by message:</label>
			<input id="log-message-filter" type="text" onchange="applyMessageFilter(this.value);"/>
		</div>
		<div class="log-setting">
			<label for="collapse-all">Collapse multi-line:</label>
			<input type="checkbox" id="collapse-all" onclick="collapseAll(this.checked);" checked>
		</div>
		<div class="log-setting">
			<label for="collapse-all">Auto scroll:</label>
			<input type="checkbox" id="auto-scroll" onclick="setAutoScroll(this.checked);" checked>
		</div>
		<div class="log-setting">
			<label>Font size:</label>
			<button id="decrease-font-size" onclick="changeFontSize(-1);">-</button>
			<button id="increase-font-size" onclick="changeFontSize(+1);">+</button>
		</div>
	</div>
	<div id="log-container" onwheel="if (window.event.deltaY < 0) setAutoScroll(false);">
		<div id="log-line-container" style="font-size: 14px"></div>
		<div id="log-msg-container"></div>
	</div>
</body>
</html>
'''

try:
	fsencoding = sys.getfilesystemencoding()
	if not fsencoding:
		raise ValueError(f"getfilesystemencoding returned {fsencoding}")
except Exception as err: # pylint: disable=broad-except
	logger.info("Problem getting filesystemencoding: %s", err)
	defaultEncoding = sys.getdefaultencoding()
	logger.notice("Patching filesystemencoding to be '%s'", defaultEncoding)
	sys.getfilesystemencoding = lambda: defaultEncoding


class WorkerOpsiclientd(WorkerOpsi):
	def __init__(self, service, request, resource):
		WorkerOpsi.__init__(self, service, request, resource)
		self._auth_module = None
		if os.name == 'posix':
			import OPSI.Backend.Manager.Authentication.PAM # pylint: disable=import-outside-toplevel
			self._auth_module = OPSI.Backend.Manager.Authentication.PAM.PAMAuthentication()
		elif os.name == 'nt':
			import OPSI.Backend.Manager.Authentication.NT # pylint: disable=import-outside-toplevel
			self._auth_module = OPSI.Backend.Manager.Authentication.NT.NTAuthentication("S-1-5-32-544")

	def run(self):
		with log_context({'instance' : 'control server'}):
			super().run() # pylint: disable=no-member

	def _getCredentials(self):
		(user, password) = self._getAuthorization()

		if not user:
			user = config.get('global', 'host_id')

		return (user, password)

	def _errback(self, failure):
		WorkerOpsi._errback(self, failure)
		logger.debug("DEBUG: detected host: '%s'", self.request.getClientIP())
		logger.debug("DEBUG: responsecode: '%s'", self.request.code)
		logger.debug("DEBUG: maxAuthenticationFailures config: '%s'", config.get('control_server', 'max_authentication_failures'))
		logger.debug("DEBUG: maxAuthenticationFailures config type: '%s'", type(config.get('control_server', 'max_authentication_failures')))

		if self.request.code == 401 and self.request.getClientIP() != "127.0.0.1":
			maxAuthenticationFailures = config.get('control_server', 'max_authentication_failures')
			if maxAuthenticationFailures > 0:
				client_ip = self.request.getClientIP()
				if client_ip not in self.service.authFailures:
					self.service.authFailures[client_ip] = {
						"count": 0,
						"blocked_time": 0
					}
				self.service.authFailures[client_ip]["count"] += 1
				if self.service.authFailures[client_ip]["count"] > maxAuthenticationFailures:
					self.service.authFailures[client_ip]["blocked_time"] = time.time()

	def _authenticate(self, result): #pylint: disable=too-many-branches
		if self.session.authenticated:
			return result

		try:
			maxAuthenticationFailures = config.get('control_server', 'max_authentication_failures')
			if maxAuthenticationFailures > 0:
				client_ip = self.request.getClientIP()
				if client_ip in self.service.authFailures and self.service.authFailures[client_ip]["blocked_time"]:
					if time.time() - self.service.authFailures[client_ip]["blocked_time"] > 60:
						# Unblock after 60 seconds
						del self.service.authFailures[client_ip]
					else:
						self.service.authFailures[client_ip]["blocked_time"] = time.time()
						raise Exception(f"{client_ip} blocked")

			(self.session.user, self.session.password) = self._getCredentials()

			logger.notice("Authorization request from %s@%s (application: %s)" % (self.session.user, self.session.ip, self.session.userAgent))

			if not self.session.password:
				raise Exception("No password from %s (application: %s)" % (self.session.ip, self.session.userAgent))

			if self.session.user.lower() == config.get('global', 'host_id').lower():
				# Auth by opsi host key
				if self.session.password != config.get('global', 'opsi_host_key'):
					raise Exception("Wrong opsi host key")
			elif self._auth_module:
				self._auth_module.authenticate(self.session.user, self.session.password)
				logger.info("Authentication successful for user '%s', groups '%s' (admin group: %s)",
					self.session.user,
					','.join(self._auth_module.get_groupnames(self.session.user)),
					self._auth_module.get_admin_groupname()
				)
				if not self._auth_module.user_is_admin(self.session.user):
					raise Exception("Not an admin user")
			else:
				raise Exception("Invalid credentials")
		except Exception as err: # pylint: disable=broad-except
			raise OpsiAuthenticationError(f"Forbidden: {err}") from err

		# Auth ok
		self.session.authenticated = True

		client_ip = self.request.getClientIP()
		if client_ip in self.service.authFailures:
			del self.service.authFailures[client_ip]

		return result


class WorkerOpsiclientdJsonRpc(WorkerOpsiclientd, WorkerOpsiJsonRpc):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)
		WorkerOpsiJsonRpc.__init__(self, service, request, resource)

	def _getCallInstance(self, result):
		self._callInstance = self.service._opsiclientdRpcInterface # pylint: disable=protected-access
		self._callInterface = self.service._opsiclientdRpcInterface.getInterface() # pylint: disable=protected-access

	def _processQuery(self, result):
		return WorkerOpsiJsonRpc._processQuery(self, result)

	def _generateResponse(self, result):
		return WorkerOpsiJsonRpc._generateResponse(self, result)

	def _renderError(self, failure):
		return WorkerOpsiJsonRpc._renderError(self, failure)


class WorkerOpsiclientdJsonInterface(WorkerOpsiclientdJsonRpc, WorkerOpsiJsonInterface):
	def __init__(self, service, request, resource):
		WorkerOpsiclientdJsonRpc.__init__(self, service, request, resource)
		WorkerOpsiJsonInterface.__init__(self, service, request, resource)
		self.path = 'interface'

	def _getCallInstance(self, result):
		return WorkerOpsiclientdJsonRpc._getCallInstance(self, result)

	def _generateResponse(self, result):
		return WorkerOpsiJsonInterface._generateResponse(self, result)

	def _renderError(self, failure):
		return WorkerOpsiJsonInterface._generateResponse(self, failure)


class WorkerCacheServiceJsonRpc(WorkerOpsiclientd, WorkerOpsiJsonRpc):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)
		WorkerOpsiJsonRpc.__init__(self, service, request, resource)

	def _getBackend(self, result):
		try:
			if self.session.callInstance and self.session.callInterface:
				return result
		except AttributeError:
			pass

		if not self.service._opsiclientd.getCacheService(): # pylint: disable=protected-access
			raise Exception('Cache service not running')

		self.session.callInstance = self.service._opsiclientd.getCacheService().getConfigBackend() # pylint: disable=protected-access
		logger.notice('Backend created: %s' % self.session.callInstance)
		self.session.callInterface = self.session.callInstance.backend_getInterface()
		return result

	def _getCallInstance(self, result):
		self._getBackend(result)
		self._callInstance = self.session.callInstance
		self._callInterface = self.session.callInterface

	def _processQuery(self, result):
		return WorkerOpsiJsonRpc._processQuery(self, result)

	def _generateResponse(self, result):
		return WorkerOpsiJsonRpc._generateResponse(self, result)

	def _renderError(self, failure):
		return WorkerOpsiJsonRpc._renderError(self, failure)


class WorkerCacheServiceJsonInterface(WorkerCacheServiceJsonRpc, WorkerOpsiJsonInterface):
	def __init__(self, service, request, resource):
		WorkerCacheServiceJsonRpc.__init__(self, service, request, resource)
		WorkerOpsiJsonInterface.__init__(self, service, request, resource)
		self.path = 'rpcinterface'

	def _getCallInstance(self, result):
		return WorkerCacheServiceJsonRpc._getCallInstance(self, result)

	def _generateResponse(self, result):
		return WorkerOpsiJsonInterface._generateResponse(self, result)

	def _renderError(self, failure):
		return WorkerOpsiJsonInterface._generateResponse(self, failure)


class WorkerOpsiclientdInfo(WorkerOpsiclientd):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)

	def _processQuery(self, result):
		return result

	def _generateResponse(self, result):
		get_event_data = False
		if b'?' in self.request.uri:
			query = self.request.uri.decode().split('?', 1)[1]
			if query == "get_event_data":
				get_event_data = True

		timeline = Timeline()
		self.request.setResponseCode(200)
		if get_event_data:
			self.request.setHeader("content-type", "application/json")
			self.request.write(json.dumps(timeline.getEventData()).encode("utf-8"))
		else:
			logger.info("Creating opsiclientd info page")
			html = INFO_PAGE % {
				"head": timeline.getHtmlHead(),
				"hostname": config.get("global", "host_id"),
			}
			self.request.setHeader("content-type", "text/html; charset=utf-8")
			self.request.write(html.encode("utf-8").strip())


class WorkerOpsiclientdUpload(WorkerOpsiclientd):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)

	def self_update_from_upload(self):
		logger.notice("Self-update from upload")
		filename = None
		file_data = self.request.content.read()
		if self.request.getHeader("Content-Type") == "multipart/form-data":
			headers = b""
			for key, value in self.request.requestHeaders.getAllRawHeaders():
				headers += key + b": " + value[0] + b"\r\n"

			msg = email.message_from_bytes(headers + b"\r\n\r\n" + file_data)
			if msg.is_multipart():
				for part in msg.walk():
					if part.get_filename():
						filename = part.get_ftmpfile
		else:
			filename = self.request.getHeader("Content-Disposition")
			if filename:
				filename = filename.split(';')[0].split('=', 1)[1]

		if filename:
			filename = filename.split("/")[-1].split("\\")[-1]

		if not filename:
			raise RuntimeError("Filename missing")

		with tempfile.TemporaryDirectory() as tmpdir:
			tmpfile = os.path.join(tmpdir, filename)
			with open(tmpfile, "wb") as file:
				file.write(file_data)
			self.service._opsiclientd.self_update_from_file(tmpfile) # pylint: disable=protected-access

	def _getQuery(self, result):
		pass

	def _processQuery(self, result):
		path = urllib.parse.unquote(self.request.path.decode("utf-8"))
		if path.startswith("/upload/update/opsiclientd"):
			try:
				self.self_update_from_upload()
			except Exception as err: # pylint: disable=broad-except
				logger.error(err, exc_info=True)
				raise
		else:
			raise ValueError("Invalid path")

	def _generateResponse(self, result):
		self.request.setResponseCode(200)
		self.request.setHeader("content-type", "text/plain; charset=utf-8")
		self.request.write("ok".encode("utf-8"))

class WorkerOpsiclientdLogViewer(WorkerOpsiclientd):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)

	def _processQuery(self, result):
		return result

	def _generateResponse(self, result):
		logger.info("Creating log viewer page")
		self.request.setResponseCode(200)
		self.request.setHeader("content-type", "text/html; charset=utf-8")
		self.request.write(LOG_VIEWER_PAGE.encode("utf-8").strip())


class ResourceRoot(Resource):
	addSlash = True
	#isLeaf = True

	def render(self, request):
		''' Process request. '''
		return b"<html><head><title>opsiclientd</title></head><body></body></html>"

class ResourceOpsiclientd(ResourceOpsi):
	WorkerClass = WorkerOpsiclientd


class ResourceOpsiclientdJsonRpc(ResourceOpsiJsonRpc):
	WorkerClass = WorkerOpsiclientdJsonRpc


class ResourceOpsiclientdJsonInterface(ResourceOpsiJsonInterface):
	WorkerClass = WorkerOpsiclientdJsonInterface


class ResourceCacheServiceJsonRpc(ResourceOpsiJsonRpc):
	WorkerClass = WorkerCacheServiceJsonRpc


class ResourceCacheServiceJsonInterface(ResourceOpsiJsonInterface):
	WorkerClass = WorkerCacheServiceJsonInterface


class ResourceOpsiclientdInfo(ResourceOpsiclientd):
	WorkerClass = WorkerOpsiclientdInfo

	def __init__(self, service):
		ResourceOpsiclientd.__init__(self, service)

class ResourceOpsiclientdLogViewer(ResourceOpsiclientd):
	WorkerClass = WorkerOpsiclientdLogViewer

	def __init__(self, service):
		ResourceOpsiclientd.__init__(self, service)

class ResourceOpsiclientdUpload(ResourceOpsiclientd):
	WorkerClass = WorkerOpsiclientdUpload


class ControlServer(OpsiService, threading.Thread): # pylint: disable=too-many-instance-attributes
	def __init__(self, opsiclientd, httpsPort, sslServerKeyFile, sslServerCertFile, staticDir=None): # pylint: disable=too-many-arguments
		OpsiService.__init__(self)
		threading.Thread.__init__(self)
		self._opsiclientd = opsiclientd
		self._httpsPort = httpsPort
		self._sslServerKeyFile = sslServerKeyFile
		self._sslServerCertFile = sslServerCertFile
		self._staticDir = staticDir
		self._root = None
		self._running = False
		self._server = None
		self._site = None
		self._opsiclientdRpcInterface = OpsiclientdRpcInterface(self._opsiclientd)

		logger.info("ControlServer initiated")
		self.authFailures = {}

	def run(self):
		with log_context({'instance' : 'control server'}):
			self._running = True
			try:
				logger.info("creating root resource")
				self.createRoot()
				self._site = server.Site(self._root)

				logger.debug('Creating SSLContext with the following values:')
				logger.debug('\t-SSL Server Key File: %s', self._sslServerKeyFile)
				if not os.path.exists(self._sslServerKeyFile):
					logger.warning(
						"The SSL server key file '%s' is missing, please check your configuration",
						self._sslServerKeyFile
					)
				logger.debug("\t-SSL Server Cert File '%s'", self._sslServerCertFile)
				if not os.path.exists(self._sslServerCertFile):
					logger.warning(
						"The SSL server certificate file '%s' is missing, please check your configuration",
						self._sslServerCertFile
					)

				self._server = reactor.listenSSL( # pylint: disable=no-member
					self._httpsPort,
					self._site,
					SSLContext(self._sslServerKeyFile, self._sslServerCertFile)
				)
				logger.notice("Control server is accepting HTTPS requests on port %d", self._httpsPort)

				if not reactor.running: # pylint: disable=no-member
					logger.debug("Reactor is not running. Starting.")
					reactor.run(installSignalHandlers=0) # pylint: disable=no-member
					logger.debug("Reactor run ended.")
				else:
					logger.debug("Reactor already running.")

			except CannotListenError as err:
				logger.critical("Failed to listen on port %s: %s", self._httpsPort, err, exc_info=True)
				self._opsiclientd.stop()
			except Exception as err: # pylint: disable=broad-except
				logger.error("ControlServer error: %s", err, exc_info=True)
			finally:
				logger.notice("Control server exiting")
				self._running = False

	def stop(self):
		if self._server:
			self._server.stopListening()
		if self._sessionHandler:
			self._sessionHandler.deleteAllSessions()
		reactor.fireSystemEvent('shutdown') # pylint: disable=no-member
		reactor.disconnectAll() # pylint: disable=no-member
		self._running = False

	def createRoot(self):
		if self._staticDir:
			if os.path.isdir(self._staticDir):
				self._root = File(self._staticDir.encode())
			else:
				logger.error("Cannot add static content '/': directory '%s' does not exist.", self._staticDir)

		if not self._root:
			self._root = ResourceRoot()

		self._root.putChild(b"opsiclientd", ResourceOpsiclientdJsonRpc(self))
		self._root.putChild(b"interface", ResourceOpsiclientdJsonInterface(self))
		self._root.putChild(b"rpc", ResourceCacheServiceJsonRpc(self))
		self._root.putChild(b"rpcinterface", ResourceCacheServiceJsonInterface(self))
		self._root.putChild(b"info.html", ResourceOpsiclientdInfo(self))
		self._root.putChild(b"log_viewer.html", ResourceOpsiclientdLogViewer(self))
		self._root.putChild(b"upload", ResourceOpsiclientdUpload(self))
		if config.get('control_server', 'kiosk_api_active'):
			self._root.putChild(b"kiosk", ResourceKioskJsonRpc(self))

		log_ws_factory = WebSocketServerFactory()
		log_ws_factory.protocol = LogWebSocketServerProtocol
		log_ws_factory.control_server = self
		ws = Resource()
		ws.putChild(b"log_viewer", WebSocketResource(log_ws_factory))
		self._root.putChild(b"ws", ws)

	def __repr__(self):
		return (
			f'<ControlServer(opsiclientd={self._opsiclientd}, httpsPort={self._httpsPort}, '
			f'sslServerKeyFile={self._sslServerKeyFile}, sslServerCertFile={self._sslServerCertFile}, '
			f'staticDir={self._staticDir})>'
		)

class RequestAdapter():
	def __init__(self, connection_request):
		self.connection_request = connection_request

	def __getattr__(self, name):
		return getattr(self.connection_request, name)

	def getClientIP(self):
		return self.connection_request.peer.split(":")[1]

	def getAllHeaders(self):
		return self.connection_request.headers

	def getHeader(self, name):
		return self.connection_request.headers.get(name)

class LogReaderThread(threading.Thread): # pylint: disable=too-many-instance-attributes
	record_start_regex = re.compile(r"^\[(\d)\]\s\[([\d\-\:\. ]+)\]\s\[([^\]]*)\]\s(.*)$")
	is_record_start_regex = re.compile(r"^\[\d\]\s\[") # should speed up matching
	max_delay = 0.2
	max_record_buffer_size = 2500

	def __init__(self, filename, websocket_protocol, num_tail_records=-1):
		super().__init__()
		self.daemon = True
		self.should_stop = False
		self.filename = filename
		self.websocket_protocol = websocket_protocol
		self.num_tail_records = int(num_tail_records)
		self.record_buffer = []
		self.send_time = 0
		self._initial_read = False

	def send_buffer(self):
		if not self.record_buffer:
			return
		data = b""
		for record in self.record_buffer:
			data += msgpack.packb(record)
		self.websocket_protocol.sendMessage(data, True)
		self.send_time = time.time()
		self.record_buffer = []

	def send_buffer_if_needed(self, max_delay=None):
		if max_delay is None:
			max_delay = self.max_delay
		if (
			self.record_buffer and
			(
				len(self.record_buffer) > self.max_record_buffer_size or
				time.time() - self.send_time > max_delay
			)
		):
			self.send_buffer()

	def parse_log_line(self, line):
		match = self.record_start_regex.match(line)
		if not match:
			if self.record_buffer:
				self.record_buffer[-1]["msg"] += f"\n{line.rstrip()}"
			return None
		context = {}
		cnum = 0
		for val in match.group(3).split(","):
			context[cnum] = val.strip()
		opsilevel = int(match.group(1))
		lvl = OPSI_LEVEL_TO_LEVEL[opsilevel]
		levelname = LEVEL_TO_NAME[lvl]
		created = datetime.datetime.strptime(match.group(2), "%Y-%m-%d %H:%M:%S.%f")
		return {
			"created": created.timestamp(),
			"context": context,
			"levelname": levelname,
			"opsilevel": opsilevel,
			"msg": match.group(4),
			"exc_text": None
		}

	def add_log_line(self, line):
		if not line:
			return
		record = self.parse_log_line(line)
		if record:
			self.record_buffer.append(record)

	def stop(self):
		self.should_stop = True

	def _get_start_position(self):
		if self.num_tail_records <= 0:
			return 0

		record_to_position = {}
		record_number = 0
		with open(self.filename, "rb") as file:
			position = 0
			for line in file:
				if self.is_record_start_regex.match(line.decode("utf-8", "replace")):
					record_number += 1
					record_to_position[record_number] = position
				position += len(line)

		if record_number <= self.num_tail_records:
			start_record = 1
			start_position = 0
		else:
			start_record = record_number - self.num_tail_records + 1
			start_position = record_to_position.get(start_record, 0)

		logger.info(
			"Setting log file start position to %d, record %d/%d",
			start_position, start_record, record_number
		)
		return start_position

	def run(self):
		try:
			start_position = self._get_start_position()
			with codecs.open(self.filename, "r", encoding="utf-8", errors="replace") as file:
				logger.debug("Start reading log file %s", self.filename)
				file.seek(start_position)
				self._initial_read = True
				# Start sending big bunches (high delay)
				max_delay = 3
				line_buffer = []
				no_line_count = 0

				while not self.should_stop:
					line = file.readline()
					if line:
						no_line_count = 0
						line_buffer.append(line)
						if len(line_buffer) >= 2 and self.is_record_start_regex.match(line_buffer[-1]):
							# Last line is a new record, not continuation text
							# Add all lines, except the last one
							for i in range(len(line_buffer) - 1):
								self.add_log_line(line_buffer[i])
							line_buffer = [line_buffer[-1]]
							self.send_buffer_if_needed(max_delay)
					else:
						if self._initial_read:
							self._initial_read = False
							max_delay = self.max_delay
						no_line_count += 1
						if no_line_count > 1:
							# Add all lines
							for line in line_buffer:
								self.add_log_line(line)
							line_buffer = []
							self.send_buffer_if_needed(max_delay)
						time.sleep(self.max_delay / 3)
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Error in log reader thread: %s", err, exc_info=True)

class LogWebSocketServerProtocol(WebSocketServerProtocol, WorkerOpsi): # pylint: disable=too-many-ancestors
	def onConnect(self, request):
		self.service = self.factory.control_server # pylint: disable=no-member
		self.request = RequestAdapter(request)
		self.log_reader_thread = None # pylint: disable=attribute-defined-outside-init

		logger.info("Client connecting to log websocket: %s", self.request.peer)
		self._getSession(None)

	def onOpen(self):
		logger.info("Log websocket connection opened (params: %s)", self.request.params)
		if not self.session or not self.session.authenticated:
			logger.error("No valid session supplied")
			self.sendClose(code=4401, reason="Unauthorized")
		else:
			num_tail_records = int(self.request.params.get("num_records", [-1])[0])
			self.log_reader_thread = LogReaderThread(config.get("global", "log_file"), self, num_tail_records) # pylint: disable=attribute-defined-outside-init
			logger.info("Starting log reader thread")
			self.log_reader_thread.start()

	def onMessage(self, payload, isBinary):
		pass

	def onClose(self, wasClean, code, reason):
		logger.info("Log websocket connection closed: %s", reason)
		if self.log_reader_thread:
			self.log_reader_thread.stop()

class OpsiclientdRpcInterface(OpsiclientdRpcPipeInterface): # pylint: disable=too-many-public-methods
	def __init__(self, opsiclientd):
		OpsiclientdRpcPipeInterface.__init__(self, opsiclientd)

	def noop(self, arg):
		pass

	def cacheService_syncConfig(self, waitForEnding=False, force=False):
		return self.opsiclientd.getCacheService().syncConfig(waitForEnding, force)

	def cacheService_getConfigCacheState(self):
		return self.opsiclientd.getCacheService().getConfigCacheState()

	def cacheService_getProductCacheState(self):
		return self.opsiclientd.getCacheService().getProductCacheState()

	def cacheService_getConfigModifications(self):
		return self.opsiclientd.getCacheService().getConfigModifications()

	def cacheService_deleteCache(self):
		cacheService = self.opsiclientd.getCacheService()
		cacheService.setConfigCacheObsolete()
		productCacheDir = cacheService.getProductCacheDir()
		if os.path.exists(productCacheDir):
			for product in os.listdir(productCacheDir):
				deleteDir = os.path.join(productCacheDir, product)
				shutil.rmtree(deleteDir)

		return "config and product cache deleted"

	def timeline_getEvents(self): # pylint: disable=no-self-use
		timeline = Timeline()
		return timeline.getEvents()

	def setBlockLogin(self, blockLogin):
		self.opsiclientd.setBlockLogin(forceBool(blockLogin))
		logger.notice("rpc setBlockLogin: blockLogin set to '%s'", self.opsiclientd._blockLogin) # pylint: disable=protected-access
		if self.opsiclientd._blockLogin: # pylint: disable=protected-access
			return "Login blocker is on"
		return "Login blocker is off"

	def readLog(self, logType='opsiclientd'): # pylint: disable=no-self-use
		logType = forceUnicode(logType)
		if logType != 'opsiclientd':
			raise ValueError(f"Unknown log type '{logType}'")

		logger.notice("rpc readLog: reading log of type '%s'", logType)

		if logType == 'opsiclientd':
			with codecs.open(config.get('global', 'log_file'), 'r', 'utf-8', 'replace') as log:
				return log.read()

		return ""

	def log_read(self, logType='opsiclientd', extension='', maxSize=5000000): # pylint: disable=no-self-use
		"""
		Return the content of a log.

		:param logType: Type of log. \
		Currently supported: *opsiclientd*, *opsi-script*, *opsi_loginblocker*, \
		*opsiclientdguard*,	'notifier_block_login',	'notifier_event', 'opsi-client-agent'
		:type data: Unicode
		:param extension: count for history log. Possible Values 0-9
		:param maxSize: Limit for the size of returned characters in bytes. \
		Setting this to `0` disables limiting.
		"""
		LOG_DIR = os.path.dirname(config.get('global', 'log_file'))
		LOG_TYPES = [  # possible logtypes
			'opsiclientd',
			'opsi-script',
			'opsi_loginblocker',
			'opsiclientdguard',
			'notifier_block_login',
			'notifier_event',
			'opsi-client-agent'
		]
		logType = forceUnicode(logType)

		if logType not in LOG_TYPES:
			raise ValueError(f'Unknown log type {logType}')

		if extension:
			extension = forceUnicode(extension)
			logFile = os.path.join(LOG_DIR, f'{logType}.log.{extension}')
			if not os.path.exists(logFile):
				# Try the other format:
				logFile = os.path.join(LOG_DIR, f'{logType}_{extension}.log')
		else:
			logFile = os.path.join(LOG_DIR, f'{logType}.log')

		try:
			with codecs.open(logFile, 'r', 'utf-8', 'replace') as log:
				data = log.read()
		except IOError as ioerr:
			if ioerr.errno == 2:  # This is "No such file or directory"
				return 'No such file or directory'
			raise

		if maxSize > 0:
			return truncateLogData(data, maxSize)

		return data

	def runCommand(self, command, sessionId=None, desktop=None):
		command = forceUnicode(command)
		if not command:
			raise ValueError("No command given")

		if sessionId:
			sessionId = forceInt(sessionId)
		else:
			sessionId = System.getActiveSessionId()
			if sessionId is None:
				sessionId = System.getActiveConsoleSessionId()

		if desktop:
			desktop = forceUnicode(desktop)
		else:
			desktop = self.opsiclientd.getCurrentActiveDesktopName()

		logger.notice("rpc runCommand: executing command '%s' in session %d on desktop '%s'", command, sessionId, desktop)
		System.runCommandInSession(
			command=command,
			sessionId=sessionId,
			desktop=desktop,
			waitForProcessEnding=False
		)
		return "command '%s' executed" % command

	def execute(self, command, waitForEnding=True, captureStderr=True, encoding=None, timeout=300): # pylint: disable=no-self-use,too-many-arguments
		return System.execute(
			cmd=command,
			waitForEnding=waitForEnding,
			captureStderr=captureStderr,
			encoding=encoding,
			timeout=timeout
		)

	def logoffSession(self, session_id = None, username = None): # pylint: disable=no-self-use
		return System.logoffSession(session_id=session_id, username=username)

	def logoffCurrentUser(self): # pylint: disable=no-self-use
		logger.notice("rpc logoffCurrentUser: logging of current user now")
		System.logoffCurrentUser()

	def lockSession(self, session_id = None, username = None): # pylint: disable=no-self-use
		return System.lockSession(session_id=session_id, username=username)

	def lockWorkstation(self): # pylint: disable=no-self-use
		logger.notice("rpc lockWorkstation: locking workstation now")
		System.lockWorkstation()

	def shutdown(self, waitSeconds=0):
		waitSeconds = forceInt(waitSeconds)
		logger.notice("rpc shutdown: shutting down computer in %s seconds", waitSeconds)
		self.opsiclientd.shutdownMachine(waitSeconds)

	def reboot(self, waitSeconds=0):
		waitSeconds = forceInt(waitSeconds)
		logger.notice("rpc reboot: rebooting computer in %s seconds", waitSeconds)
		self.opsiclientd.rebootMachine(waitSeconds)

	def restart(self, waitSeconds=0):
		waitSeconds = forceInt(waitSeconds)
		logger.notice("rpc restart: restarting opsiclientd in %s seconds", waitSeconds)
		self.opsiclientd.restart(waitSeconds)

	def uptime(self):
		uptime = int(time.time() - self.opsiclientd._startupTime) # pylint: disable=protected-access
		logger.notice("rpc uptime: opsiclientd is running for %d seconds", uptime)
		return uptime

	def fireEvent(self, name): # pylint: disable=no-self-use
		event = getEventGenerator(name)
		logger.notice("Firing event '%s'" % name)
		event.createAndFireEvent()

	def setStatusMessage(self, sessionId, message):
		sessionId = forceInt(sessionId)
		message = forceUnicode(message)
		ept = self.opsiclientd.getEventProcessingThread(sessionId)
		logger.notice("rpc setStatusMessage: Setting status message to '%s'", message)
		ept.setStatusMessage(message)

	def isEventRunning(self, name):
		running = False
		for ept in self.opsiclientd.getEventProcessingThreads():
			if ept.event.eventConfig.getId() == name:
				running = True
				break
		return running

	def getRunningEvents(self):
		"""
		Returns a list with running events.
		"""
		running = [ept.event.eventConfig.getId() for ept in self.opsiclientd.getEventProcessingThreads()]
		if not running:
			logger.debug("Currently no event is running.")
		return running

	def isInstallationPending(self):
		return forceBool(self.opsiclientd.isInstallationPending())

	def getCurrentActiveDesktopName(self, sessionId=None):
		desktop = self.opsiclientd.getCurrentActiveDesktopName(sessionId)
		logger.notice(
			"rpc getCurrentActiveDesktopName: current active desktop name is %s",
			desktop
		)
		return desktop

	def setCurrentActiveDesktopName(self, sessionId, desktop):
		sessionId = forceInt(sessionId)
		desktop = forceUnicode(desktop)
		self.opsiclientd._currentActiveDesktopName[sessionId] = desktop # pylint: disable=protected-access
		logger.notice(
			"rpc setCurrentActiveDesktopName: current active desktop name for session %s set to '%s'",
			sessionId, desktop
		)

	def switchDesktop(self, desktop, sessionId=None):
		self.opsiclientd.switchDesktop(desktop, sessionId)

	def getConfig(self): # pylint: disable=no-self-use
		return config.getDict()

	def getConfigValue(self, section, option): # pylint: disable=no-self-use
		section = forceUnicode(section)
		option = forceUnicode(option)
		return config.get(section, option)

	def setConfigValue(self, section, option, value): # pylint: disable=no-self-use
		section = forceUnicode(section)
		option = forceUnicode(option)
		value = forceUnicode(value)
		return config.set(section, option, value)

	def set(self, section, option, value):
		# Legacy method
		return self.setConfigValue(section, option, value)

	def readConfigFile(self): # pylint: disable=no-self-use
		config.readConfigFile()

	def updateConfigFile(self, force=False): # pylint: disable=no-self-use
		config.updateConfigFile(force)

	def showPopup(self, message, mode='prepend', addTimestamp=True):
		message = forceUnicode(message)
		self.opsiclientd.showPopup(message, mode, addTimestamp)

	def deleteServerCerts(self): # pylint: disable=no-self-use
		cert_dir = config.get('global', 'server_cert_dir')
		if os.path.exists(cert_dir):
			for filename in os.listdir(cert_dir):
				if os.path.basename(config.ca_cert_file).lower() in filename.strip().lower():
					continue
				os.remove(os.path.join(cert_dir, filename))

	def updateOpsiCaCert(self, ca_cert_pem): # pylint: disable=no-self-use
		ca_certs = []
		for match in re.finditer(r"(-+BEGIN CERTIFICATE-+.*?-+END CERTIFICATE-+)", ca_cert_pem, re.DOTALL):
			try:
				ca_certs.append(
					crypto.load_certificate(crypto.FILETYPE_PEM, match.group(1).encode("utf-8"))
				)
			except Exception as err: # pylint: disable=broad-except
				logger.error(err, exc_info=True)

		if ca_certs:
			if not os.path.isdir(os.path.dirname(config.ca_cert_file)):
				os.makedirs(os.path.dirname(config.ca_cert_file))
			with open(config.ca_cert_file, "wb") as file:
				for cert in ca_certs:
					file.write(crypto.dump_certificate(crypto.FILETYPE_PEM, cert))

	def getActiveSessions(self): # pylint: disable=no-self-use
		sessions = System.getActiveSessionInformation()
		for session in sessions:
			session["LogonDomain"] = session.get("DomainName")
		return sessions

	def getBackendInfo(self): # pylint: disable=no-self-use
		serviceConnection = ServiceConnection(loadBalance=False)
		serviceConnection.connectConfigService()
		backendinfo = None
		try:
			configService = serviceConnection.getConfigService()
			backendinfo = configService.backend_info()
		finally:
			serviceConnection.disconnectConfigService()

		return backendinfo

	def getState(self, name, default=None): # pylint: disable=no-self-use
		"""
		Return a specified state.

		:param name: Name of the state.
		:param default: Default value if something goes wrong.
		"""
		return state.get(name, default)

	def setState(self, name, value): # pylint: disable=no-self-use
		"""
		Set a specified state.

		:param name: Name of the State.
		:param value: Value to set the state.
		"""
		return state.set(name, value)

	def updateComponent(self, component, url):
		if component != "opsiclientd":
			raise ValueError(f"Invalid component {component}")
		return self.opsiclientd.self_update_from_url(url)

	def execPythonCode(self, code): # pylint: disable=no-self-use
		""" Execute lines of python code, returns the result of the last line """
		code = code.split("\n")
		exec("\n".join(code[:-1])) # pylint: disable=exec-used
		return eval(code[-1]) # pylint: disable=eval-used

	def loginUser(self, username, password):
		try:
			secret_filter.add_secrets(password)
			return self.opsiclientd.loginUser(username, password)
		except Exception as err: # pylint: disable=broad-except
			logger.error(err, exc_info=True)
			raise

	def loginOpsiSetupAdmin(self, recreate_user=False):
		for session_id in System.getUserSessionIds("opsisetupadmin"):
			System.logoffSession(session_id)
		user_info = self.opsiclientd.createOpsiSetupAdmin(delete_existing=recreate_user)
		return self.opsiclientd.loginUser(user_info["name"], user_info["password"])

	def runAsOpsiSetupAdmin(self, command="powershell.exe -ExecutionPolicy ByPass", recreate_user=False):
		try:
			# https://bugs.python.org/file46988/issue.py
			if not RUNNING_ON_WINDOWS:
				raise NotImplementedError(f"Not implemented on {platform.system()}")
			# pyright: reportMissingImports=false
			import win32profile # pylint: disable=import-error,import-outside-toplevel
			import win32security # pylint: disable=import-error,import-outside-toplevel
			import winreg # pylint: disable=import-error,import-outside-toplevel

			for session_id in System.getUserSessionIds("opsisetupadmin"):
				System.logoffSession(session_id)
			user_info = self.opsiclientd.createOpsiSetupAdmin(delete_existing=recreate_user)

			logon = win32security.LogonUser(
				user_info["name"], None, user_info["password"],
				win32security.LOGON32_LOGON_INTERACTIVE,
				win32security.LOGON32_PROVIDER_DEFAULT
			)
			try:
				# This will create the user home dir and ntuser.dat gets loaded
				hkey = win32profile.LoadUserProfile(logon, {"UserName": user_info["name"]})
				try:
					#env = win32profile.CreateEnvironmentBlock(logon, False)
					str_sid = win32security.ConvertSidToStringSid(user_info["user_sid"])
					reg_key = winreg.OpenKey(
						winreg.HKEY_USERS,
						str_sid + r'\Software\Microsoft\Windows NT\CurrentVersion\Winlogon',
						0,
						winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY
					)
					with reg_key:
						winreg.SetValueEx(reg_key, "Shell", 0, winreg.REG_SZ, command)
				finally:
					win32profile.UnloadUserProfile(logon, hkey)
			finally:
				logon.close()

			if not self.opsiclientd._controlPipe.credentialProviderConnected(): # pylint: disable=protected-access
				for _unused in range(20):
					if self.opsiclientd._controlPipe.credentialProviderConnected(): # pylint: disable=protected-access
						break
					time.sleep(0.5)

			self.opsiclientd.loginUser(user_info["name"], user_info["password"])
		except Exception as err: # pylint: disable=broad-except
			logger.error(err, exc_info=True)
			raise

	def runOnShutdown(self):
		on_shutdown_active = False
		for event_config in getEventConfigs().values():
			if event_config["name"] == "on_shutdown" and event_config["active"]:
				on_shutdown_active = True
				break

		if not on_shutdown_active:
			logger.info("on_shutdown event is not active")
			return False

		if self.isInstallationPending():
			logger.info("Installation are pending, not firing on_shutdown")
			return False

		logger.info("Firing on_shutdown and waiting for event to complete")
		self.fireEvent("on_shutdown")
		time.sleep(10)
		while self.isEventRunning("on_shutdown"):
			time.sleep(10)

		logger.info("on_shutdown event completed")
		return True
