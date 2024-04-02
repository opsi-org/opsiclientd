# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Server component for controlling opsiclientd.

These classes are used to create a https service which executes remote
procedure calls
"""

import codecs
import datetime
import email
import json
import os
import platform
import re
import socket
import sys
import tempfile
import threading
import time
import urllib
import warnings
from collections import namedtuple
from types import ModuleType

import msgpack  # type: ignore[import]
from OpenSSL import SSL

with warnings.catch_warnings():
	warnings.filterwarnings("ignore", category=DeprecationWarning)
	from autobahn.twisted.resource import WebSocketResource  # type: ignore[import]
	from autobahn.twisted.websocket import (  # type: ignore[import]
		WebSocketServerFactory,
		WebSocketServerProtocol,
	)

from OPSI.Service import OpsiService  # type: ignore[import]
from OPSI.Service.Resource import (  # type: ignore[import]
	ResourceOpsi,
	ResourceOpsiJsonInterface,
	ResourceOpsiJsonRpc,
)
from OPSI.Service.Worker import (  # type: ignore[import]
	WorkerOpsi,
	WorkerOpsiJsonInterface,
	WorkerOpsiJsonRpc,
)
from opsicommon.exceptions import OpsiServiceAuthenticationError
from opsicommon.logging import (
	LEVEL_TO_NAME,
	OPSI_LEVEL_TO_LEVEL,
	get_logger,
	log_context,
)
from twisted.internet import fdesc
from twisted.internet.abstract import isIPv6Address
from twisted.internet.base import BasePort
from twisted.internet.error import CannotListenError
from twisted.web import server
from twisted.web.resource import Resource
from twisted.web.static import File

from opsiclientd import __version__
from opsiclientd.Config import Config
from opsiclientd.SoftwareOnDemand import ResourceKioskJsonRpc
from opsiclientd.State import State
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS
from opsiclientd.Timeline import Timeline
from opsiclientd.webserver.rpc.control import ControlInterface

config = Config()
state = State()
logger = get_logger("opsiclientd")
twisted_reactor: ModuleType | None = None


def get_twisted_reactor() -> ModuleType:
	global twisted_reactor  # pylint: disable=global-statement
	if twisted_reactor is None:
		logger.info("Installing twisted reactor")
		from twisted.internet import reactor

		twisted_reactor = reactor
	assert twisted_reactor
	return twisted_reactor


class SSLContext(object):
	def __init__(self, sslServerKeyFile, sslServerCertFile, acceptedCiphers=""):
		"""
		Create a context for the usage of SSL in twisted.

		:param sslServerCertFile: Path to the certificate file.
		:type sslServerCertFile: str
		:param sslServerKeyFile: Path to the key file.
		:type sslServerKeyFile: str
		:param acceptedCiphers: A string defining what ciphers should \
be accepted. Please refer to the OpenSSL documentation on how such a \
string should be composed. No limitation will be done if an empty value \
is set.
		:type acceptedCiphers: str
		"""
		self._sslServerKeyFile = sslServerKeyFile
		self._sslServerCertFile = sslServerCertFile
		self._acceptedCiphers = acceptedCiphers

	def getContext(self):
		"""
		Get an SSL context.

		:rtype: OpenSSL.SSL.Context
		"""

		# Test if server certificate and key file exist.
		if not os.path.isfile(self._sslServerKeyFile):
			raise OSError(f"Server key file '{self._sslServerKeyFile}' does not exist!")

		if not os.path.isfile(self._sslServerCertFile):
			raise OSError(f"Server certificate file '{self._sslServerCertFile}' does not exist!")

		context = SSL.Context(SSL.SSLv23_METHOD)
		context.use_privatekey_file(self._sslServerKeyFile)
		context.use_certificate_file(self._sslServerCertFile)

		if self._acceptedCiphers:
			context.set_cipher_list(self._acceptedCiphers)

		return context


INDEX_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">

<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<meta http-equiv="Content-Type" content="text/xhtml; charset=utf-8" />
	<title>opsi client daemon</title>
	<link rel="stylesheet" type="text/css" href="/opsiclientd.css" />
</head>
<body>
	<p id="title">opsiclientd on host %(hostname)s</p>
	<div class="mainpage-link-box">
		<ul>
			<li><a target="_blank" href="info.html">opsiclientd info page</a></li>
			<li><a target="_blank" href="log_viewer.html">opsiclientd log viewer</a></li>
			<li><a target="_blank" href="interface">opsiclientd control interface</a></li>
		</ul>
	</div>

</body>
</html>
"""

INFO_PAGE = """<!DOCTYPE html>
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
"""

LOG_VIEWER_PAGE = """<!DOCTYPE html>
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
"""

TERMINAL_PAGE = """<!DOCTYPE html>
<html>
<head>
	<title>opsiclientd - terminal</title>
	<link rel="stylesheet" href="/opsiclientd.css" />
	<link rel="stylesheet" href="/xterm/xterm.css" />
	<script src="/xterm/xterm.js"></script>
	<script src="/xterm/fit.js"></script>
	<script src="/xterm/fullscreen.js"></script>
	<script src="/xterm/search.js"></script>
	<script src="/xterm/webLinks.js"></script>
	<script>
		var term;
		var ws;

		function runTerminal() {
			Terminal.applyAddon(fullscreen)
			Terminal.applyAddon(fit)
			Terminal.applyAddon(search)
			Terminal.applyAddon(webLinks)
			term = new Terminal({
				cursorBlink: true,
				macOptionIsMeta: true,
				scrollback: 1000,
				fontSize: 14,
				//lineHeight: 1.1
			});
			term.open(document.getElementById('terminal'));
			term.fit()
			//term.resize(columns, lines)
			console.log(`size: ${term.cols} columns, ${term.rows} rows`)

			term.on('key', (key, ev) => {
				//console.debug("pressed key", key);
				//console.debug("event", ev);
				ws.send(key);
			});

			term.on('paste', function (data, ev) {
				ws.send(data);
			});

			var params = [`lines=${term.rows}`, `columns=${term.cols}`]
			var loc = window.location;
			var ws_uri;
			if (loc.protocol == "https:") {
				ws_uri = "wss:";
			} else {
				ws_uri = "ws:";
			}
			ws_uri += "//" + loc.host;
			ws = new WebSocket(ws_uri + "/ws/terminal?" + params.join('&'));

			ws.onmessage = function (evt) {
				evt.data.text().then(text => {
					//console.debug(text);
					term.write(text);
				});
			};

			ws.onclose = function() {
				console.log("Terminal ws connection closed...");
			};
		}
	</script>
</head>
<body style="background-color: #000000; margin: 5px;" onload="runTerminal();">
	<!--
	<button onclick="term.setOption('fontSize', term.getOption('fontSize') + 1);">+</button>
	<button onclick="term.setOption('fontSize', term.getOption('fontSize') - 1);">-</button>
	-->
	<div style="width: 100%; height: 100%; position: absolute; margin:auto;" id="terminal"></div>
</body>
</html>
"""

try:
	fsencoding = sys.getfilesystemencoding()
	if not fsencoding:
		raise ValueError(f"getfilesystemencoding returned {fsencoding}")
except Exception as fse_err:
	logger.info("Problem getting filesystemencoding: %s", fse_err)
	defaultEncoding = sys.getdefaultencoding()
	logger.notice("Patching filesystemencoding to be '%s'", defaultEncoding)
	sys.getfilesystemencoding = lambda: defaultEncoding

if platform.system().lower() == "windows":

	def create_dualstack_internet_socket(self):
		logger.info("Creating DualStack socket.")
		skt = socket.socket(self.addressFamily, self.socketType)
		skt.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
		skt.setblocking(False)
		fdesc._setCloseOnExec(skt.fileno())
		return skt

	# Monkeypatch createInternetSocket to enable dual stack connections
	BasePort.createInternetSocket = create_dualstack_internet_socket  # type: ignore[method-assign]


class WorkerOpsiclientd(WorkerOpsi):
	def __init__(self, service, request, resource):
		WorkerOpsi.__init__(self, service, request, resource)
		self._auth_module = None
		self._set_auth_module()

	def _set_auth_module(self):
		self._auth_module = None
		if os.name == "posix":
			import OPSI.Backend.Manager.Authentication.PAM  # type: ignore[import]

			self._auth_module = OPSI.Backend.Manager.Authentication.PAM.PAMAuthentication()
		elif os.name == "nt":
			import OPSI.Backend.Manager.Authentication.NT  # type: ignore[import]

			self._auth_module = OPSI.Backend.Manager.Authentication.NT.NTAuthentication("S-1-5-32-544")

	def run(self):
		with log_context({"instance": "control server"}):
			super().run()

	def _getCredentials(self):
		(user, password) = self._getAuthorization()

		if not user:
			user = config.get("global", "host_id")

		return (user.lower(), password)

	def _errback(self, failure):
		client_ip = self.request.getClientAddress().host
		if self.request.code == 401 and client_ip not in ("127.0.0.1", "::ffff:127.0.0.1", "::1"):
			maxAuthenticationFailures = config.get("control_server", "max_authentication_failures")
			if maxAuthenticationFailures > 0:
				if client_ip not in self.service.authFailures:
					self.service.authFailures[client_ip] = {"count": 0, "blocked_time": 0}
				self.service.authFailures[client_ip]["count"] += 1
				if self.service.authFailures[client_ip]["count"] > maxAuthenticationFailures:
					self.service.authFailures[client_ip]["blocked_time"] = time.time()
			get_twisted_reactor().callLater(5, WorkerOpsi._errback, self, failure)
		else:
			WorkerOpsi._errback(self, failure)

	def _authenticate(self, result):
		if self.session.authenticated:
			return result

		try:
			maxAuthenticationFailures = config.get("control_server", "max_authentication_failures")
			if maxAuthenticationFailures > 0:
				client_ip = self.request.getClientAddress().host
				if client_ip in self.service.authFailures and self.service.authFailures[client_ip]["blocked_time"]:
					if time.time() - self.service.authFailures[client_ip]["blocked_time"] > 60:
						# Unblock after 60 seconds
						del self.service.authFailures[client_ip]
					else:
						self.service.authFailures[client_ip]["blocked_time"] = time.time()
						raise RuntimeError(f"{client_ip} blocked")

			(self.session.user, self.session.password) = self._getCredentials()
			logger.notice("Authorization request from %s@%s (application: %s)", self.session.user, self.session.ip, self.session.userAgent)

			if not self.session.password:
				raise RuntimeError(f"No password from {self.session.ip} (application: {self.session.userAgent}")

			if self.session.user.lower() == config.get("global", "host_id").lower():
				# Auth by opsi host key
				if self.session.password != config.get("global", "opsi_host_key"):
					raise RuntimeError("Wrong opsi host key")
			elif self._auth_module:
				self._auth_module.authenticate(self.session.user, self.session.password)
				logger.info(
					"Authentication successful for user '%s', groups '%s' (admin group: %s)",
					self.session.user,
					",".join(self._auth_module.get_groupnames(self.session.user)),
					self._auth_module.get_admin_groupname(),
				)
				if not self._auth_module.user_is_admin(self.session.user):
					raise RuntimeError("Not an admin user")
			else:
				raise RuntimeError("Invalid credentials")
		except Exception as err:
			self.request.code = 401
			raise OpsiServiceAuthenticationError(f"Forbidden: {err}") from err

		# Auth ok
		self.session.authenticated = True

		client_ip = self.request.getClientAddress().host
		if client_ip in self.service.authFailures:
			del self.service.authFailures[client_ip]

		return result


class WorkerOpsiclientdJsonRpc(WorkerOpsiclientd, WorkerOpsiJsonRpc):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)
		WorkerOpsiJsonRpc.__init__(self, service, request, resource)

	def _getCallInstance(self, result):
		self._callInstance = self.service._opsiclientdRpcInterface
		self._callInterface = self.service._opsiclientdRpcInterface.getInterface()

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
		self.path = "interface"

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

		if not self.service._opsiclientd.getCacheService():
			raise RuntimeError("Cache service not running")

		self.session.callInstance = self.service._opsiclientd.getCacheService().getConfigBackend()
		logger.notice("Backend created: %s", self.session.callInstance)
		self.session.callInterface = self.session.callInstance.backend_getInterface()
		return result

	def _getCallInstance(self, result):
		self._getBackend(result)
		self._callInstance = self.session.callInstance
		self._callInterface = self.session.callInterface

	def _processQuery(self, result):
		return WorkerOpsiJsonRpc._processQuery(self, result)

	def _generateResponse(self, result):
		cache_service = self.service._opsiclientd.getCacheService()
		if not cache_service:
			raise RuntimeError("Cache service not running")
		self.request.setHeader(
			b"server", f"opsiclientd config cache service {cache_service.getConfigCacheState().get('server_version', '4.2.0.0')}"
		)
		return WorkerOpsiJsonRpc._generateResponse(self, result)

	def _renderError(self, failure):
		return WorkerOpsiJsonRpc._renderError(self, failure)


class WorkerCacheServiceJsonInterface(WorkerCacheServiceJsonRpc, WorkerOpsiJsonInterface):
	def __init__(self, service, request, resource):
		WorkerCacheServiceJsonRpc.__init__(self, service, request, resource)
		WorkerOpsiJsonInterface.__init__(self, service, request, resource)
		self.path = "rpcinterface"

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
		if b"?" in self.request.uri:
			query = self.request.uri.decode().split("?", 1)[1]
			if query == "get_event_data":
				get_event_data = True

		timeline = Timeline()
		self.request.setResponseCode(200)
		if get_event_data:
			self.request.setHeader("Content-Type", "application/json")
			self.request.write(json.dumps(timeline.getEventData()).encode("utf-8"))
		else:
			logger.info("Creating opsiclientd info page")
			html = INFO_PAGE % {
				"head": timeline.getHtmlHead(),
				"hostname": config.get("global", "host_id"),
			}
			self.request.setHeader("Content-Type", "text/html; charset=utf-8")
			self.request.write(html.encode("utf-8").strip())


class WorkerOpsiclientdFiles(WorkerOpsiclientd):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)

	def _generateResponse(self, result):
		path = urllib.parse.unquote(self.request.path.decode("utf-8"))
		query = {}
		if b"?" in self.request.uri:
			query = urllib.parse.parse_qs(self.request.uri.decode("utf-8").split("?", 1)[1])
		logger.info("Requested endpoint %s with query %s", path, query)
		if path == "/files/logs":
			file_path = self.service._opsiclientd.collectLogfiles(
				types=query.get("type", []), max_age_days=query.get("max_age_days", [None])[0]
			)
			logger.notice("Delivering file %s", file_path)
			self.request.setResponseCode(200)
			self.request.setHeader("Content-Type", "application/octet-stream")
			self.request.setHeader("Content-Disposition", f"attachment; filename='{file_path.name}'")
			with open(str(file_path), "rb") as body_file:
				chunk_size = 65536
				while True:
					data = body_file.read(chunk_size)
					if not data:
						break
					self.request.write(data)
			file_path.unlink()  # Delete file after successfull download
		else:
			self.request.setResponseCode(404)
			self.request.setHeader("Content-Type", "text/plain; charset=utf-8")
			self.request.write(f"Endpoint {path} unknown".encode("utf-8"))


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
				filename = filename.split(";")[0].split("=", 1)[1]

		if filename:
			filename = filename.split("/")[-1].split("\\")[-1]

		if not filename:
			raise RuntimeError("Filename missing")

		with tempfile.TemporaryDirectory() as tmpdir:
			tmpfile = os.path.join(tmpdir, filename)
			with open(tmpfile, "wb") as file:
				file.write(file_data)
			self.service._opsiclientd.self_update_from_file(tmpfile)

	def _getQuery(self, result):
		pass

	def _processQuery(self, result):
		path = urllib.parse.unquote(self.request.path.decode("utf-8"))
		if path.startswith("/upload/update/opsiclientd"):
			try:
				self.self_update_from_upload()
			except Exception as err:
				logger.error(err, exc_info=True)
				raise
		else:
			raise ValueError("Invalid path")

	def _generateResponse(self, result):
		self.request.setResponseCode(200)
		self.request.setHeader("Content-Type", "text/plain; charset=utf-8")
		self.request.write("ok".encode("utf-8"))


class WorkerOpsiclientdLogViewer(WorkerOpsiclientd):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)

	def _processQuery(self, result):
		return result

	def _generateResponse(self, result):
		logger.info("Creating log viewer page")
		self.request.setResponseCode(200)
		self.request.setHeader("Content-Type", "text/html; charset=utf-8")
		self.request.write(LOG_VIEWER_PAGE.encode("utf-8").strip())


class WorkerOpsiclientdTerminal(WorkerOpsiclientd):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)

	def _processQuery(self, result):
		return result

	def _generateResponse(self, result):
		logger.info("Creating terminal page")
		self.request.setResponseCode(200)
		self.request.setHeader("Content-Type", "text/html; charset=utf-8")
		self.request.write(TERMINAL_PAGE.encode("utf-8").strip())


class ResourceRoot(Resource):
	addSlash = True

	def render(self, request):
		"""Process request."""
		request.setHeader(b"server", f"opsiclientd {__version__}")
		return b"<html><head><title>opsiclientd</title></head><body></body></html>"


class ResourceOpsiclientdIndex(Resource):
	def __init__(self, service):
		super().__init__()

	def render(self, request):
		request.setHeader(b"server", f"opsiclientd {__version__}")
		return (INDEX_PAGE % {"hostname": config.get("global", "host_id")}).encode("utf-8")


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


class ResourceOpsiclientdFiles(ResourceOpsiclientd):
	WorkerClass = WorkerOpsiclientdFiles


class ResourceOpsiclientdLogViewer(ResourceOpsiclientd):
	WorkerClass = WorkerOpsiclientdLogViewer

	def __init__(self, service):
		ResourceOpsiclientd.__init__(self, service)


class ResourceOpsiclientdTerminal(ResourceOpsiclientd):
	WorkerClass = WorkerOpsiclientdTerminal

	def __init__(self, service):
		ResourceOpsiclientd.__init__(self, service)


class ResourceOpsiclientdUpload(ResourceOpsiclientd):
	WorkerClass = WorkerOpsiclientdUpload


class ControlServer(OpsiService, threading.Thread):
	def __init__(self, opsiclientd) -> None:
		OpsiService.__init__(self)
		threading.Thread.__init__(self, name="ControlServer")
		self._opsiclientd = opsiclientd
		self._interface = config.get("control_server", "interface") or "::"
		self._httpsPort = config.get("control_server", "port")
		self._sslServerKeyFile = config.get("control_server", "ssl_server_key_file")
		self._sslServerCertFile = config.get("control_server", "ssl_server_cert_file")
		self._staticDir = config.get("control_server", "static_dir")
		self._startDelay = config.get("control_server", "start_delay") or 0
		self._root = None
		self._running = False
		self._should_stop = False
		self._server = None
		self._site = None
		self._opsiclientdRpcInterface = ControlInterface(self._opsiclientd)

		logger.info("ControlServer initiated")
		self.authFailures: dict[str, dict[str, int]] = {}

	def run(self):
		with log_context({"instance": "control server"}):
			self._running = True
			try:
				logger.info("Creating root resource")
				self.createRoot()
				self._site = server.Site(self._root)

				logger.debug("Creating SSLContext with the following values:")
				logger.debug("\t-SSL Server Key %r", self._sslServerKeyFile)
				if not os.path.exists(self._sslServerKeyFile):
					logger.warning("The SSL server key file '%s' is missing, please check your configuration", self._sslServerKeyFile)
				logger.debug("\t-SSL Server Cert %r", self._sslServerCertFile)
				if not os.path.exists(self._sslServerCertFile):
					logger.warning(
						"The SSL server certificate file '%s' is missing, please check your configuration", self._sslServerCertFile
					)

				if self._startDelay and self._startDelay > 0:
					logger.notice("Starting control server with delay of %d seconds", self._startDelay)
					for _ in range(self._startDelay):
						if self._should_stop:
							return
						time.sleep(1)

				reactor = get_twisted_reactor()
				ssl_context = SSLContext(self._sslServerKeyFile, self._sslServerCertFile)
				is_ipv6 = isIPv6Address(self._interface)
				try:
					self._server = reactor.listenSSL(self._httpsPort, self._site, ssl_context, interface=self._interface)
					if is_ipv6:
						logger.info("IPv6 support enabled")
				except Exception as err:
					if not is_ipv6 or self._interface != "::":
						raise
					logger.info("No IPv6 support: %s", err)
					self._server = reactor.listenSSL(self._httpsPort, self._site, ssl_context, interface=self._interface)
				logger.notice("Control server is accepting HTTPS requests on address [%s]:%d", self._interface, self._httpsPort)

				if not reactor.running:
					logger.debug("Reactor is not running. Starting.")
					reactor.run(installSignalHandlers=0)
					logger.debug("Reactor run ended.")
				else:
					logger.debug("Reactor already running.")
					while not self._should_stop and reactor.running:
						time.sleep(1)

			except CannotListenError as err:
				logger.critical("Failed to listen on port %s: %s", self._httpsPort, err, exc_info=True)
				self._opsiclientd.stop()
			except Exception as err:
				logger.error("ControlServer error: %s", err, exc_info=True)
			finally:
				logger.notice("Control server exiting")
				self._running = False

	def stop(self):
		self._should_stop = True
		if self._server:
			self._server.stopListening()
		if self._sessionHandler:
			self._sessionHandler.deleteAllSessions()
		reactor = get_twisted_reactor()
		reactor.fireSystemEvent("shutdown")
		reactor.disconnectAll()
		self._running = False

	def createRoot(self):
		if self._staticDir:
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
		self._root.putChild(b"terminal.html", ResourceOpsiclientdTerminal(self))
		self._root.putChild(b"upload", ResourceOpsiclientdUpload(self))
		self._root.putChild(b"files", ResourceOpsiclientdFiles(self))
		self._root.putChild(b"index.html", ResourceOpsiclientdIndex(self))
		self._root.putChild(b"", ResourceOpsiclientdIndex(self))
		if config.get("control_server", "kiosk_api_active"):
			self._root.putChild(b"kiosk", ResourceKioskJsonRpc(self))

		log_ws_factory = WebSocketServerFactory()
		log_ws_factory.protocol = LogWebSocketServerProtocol
		log_ws_factory.control_server = self

		terminal_ws_factory = WebSocketServerFactory()
		terminal_ws_factory.protocol = TerminalWebSocketServerProtocol
		terminal_ws_factory.control_server = self

		ws = Resource()
		ws.putChild(b"log_viewer", WebSocketResource(log_ws_factory))
		ws.putChild(b"terminal", WebSocketResource(terminal_ws_factory))
		self._root.putChild(b"ws", ws)

	def __repr__(self):
		return (
			f"<ControlServer(opsiclientd={self._opsiclientd}, httpsPort={self._httpsPort}, "
			f"sslServerKeyFile={self._sslServerKeyFile}, sslServerCertFile={self._sslServerCertFile}, "
			f"staticDir={self._staticDir})>"
		)


ClientAddress = namedtuple("ClientAddress", ["type", "host", "port"])


class RequestAdapter:
	def __init__(self, connection_request):
		self.connection_request = connection_request

	def __getattr__(self, name):
		return getattr(self.connection_request, name)

	def getClientAddress(self):
		parts = self.connection_request.peer.split(":")
		host = ":".join(parts[1:-1]).replace("[", "").replace("]", "")
		logger.debug("Creating ClientAddress with parameters '%s', '%s' and '%s'", parts[0], host, parts[-1])
		# In case of ipv6 connection, host may contain ":"
		return ClientAddress(parts[0], host, parts[-1])

	def getAllHeaders(self):
		return self.connection_request.headers

	def getHeader(self, name):
		for header in self.connection_request.headers:
			if header.lower() == name.lower():
				return self.connection_request.headers[header]
		return None


class LogReaderThread(threading.Thread):
	record_start_regex = re.compile(r"^\[(\d)\]\s\[([\d\-\:\. ]+)\]\s\[([^\]]*)\]\s(.*)$")
	is_record_start_regex = re.compile(r"^\[\d\]\s\[")  # should speed up matching
	max_delay = 0.2
	max_record_buffer_size = 2500

	def __init__(self, filename, websocket_protocol, num_tail_records=-1):
		super().__init__(daemon=True, name="LogReaderThread")
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
		get_twisted_reactor().callFromThread(self.websocket_protocol.sendMessage, data, True)
		self.send_time = time.time()
		self.record_buffer = []

	def send_buffer_if_needed(self, max_delay=None):
		if max_delay is None:
			max_delay = self.max_delay
		if self.record_buffer and (len(self.record_buffer) > self.max_record_buffer_size or time.time() - self.send_time > max_delay):
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
			"exc_text": None,
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

		logger.info("Setting log file start position to %d, record %d/%d", start_position, start_record, record_number)
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
		except Exception as err:
			logger.error("Error in log reader thread: %s", err, exc_info=True)


class LogWebSocketServerProtocol(WebSocketServerProtocol, WorkerOpsiclientd):
	def onConnect(self, request):
		self.service = self.factory.control_server
		self.request = RequestAdapter(request)
		self.log_reader_thread = None

		logger.info("Client connecting to log websocket: %s", self.request.peer)
		self._set_auth_module()
		self._getSession(None)
		try:
			self._authenticate(None)
		except Exception as err:
			logger.warning("Authentication error: %s", err)
			self.session.authenticated = False

	def onOpen(self):
		logger.info("Log websocket connection opened (params: %s)", self.request.params)
		if not self.session or not self.session.authenticated:
			logger.error("No valid session supplied")
			self.sendClose(code=4401, reason="Unauthorized")
		else:
			num_tail_records = int(self.request.params.get("num_records", [-1])[0])
			self.log_reader_thread = LogReaderThread(config.get("global", "log_file"), self, num_tail_records)
			logger.info("Starting log reader thread")
			self.log_reader_thread.start()

	def onMessage(self, payload, isBinary):
		pass

	def onClose(self, wasClean, code, reason):
		logger.info("Log websocket connection closed: %s", reason)
		if self.log_reader_thread:
			self.log_reader_thread.stop()


class TerminalReaderThread(threading.Thread):
	def __init__(self, websocket_protocol):
		super().__init__(daemon=True, name="TerminalReaderThread")
		self.should_stop = False
		self.websocket_protocol = websocket_protocol

	def run(self):
		reactor = get_twisted_reactor()
		while not self.should_stop:
			try:
				data = self.websocket_protocol.child_read(16 * 1024)
				if not data:  # EOF.
					break
				if not self.should_stop:
					reactor.callFromThread(self.websocket_protocol.send, data)
				time.sleep(0.001)
			except socket.timeout:
				continue
			except (IOError, EOFError) as err:
				logger.debug(err)
				break
			except Exception as err:
				if not self.should_stop:
					logger.error("Error in terminal reader thread: %s %s", err.__class__, err, exc_info=True)
					time.sleep(1)

	def stop(self):
		self.should_stop = True


class TerminalWebSocketServerProtocol(WebSocketServerProtocol, WorkerOpsiclientd):
	def onConnect(self, request):
		self.service = self.factory.control_server
		self.request = RequestAdapter(request)
		self.terminal_reader_thread = None
		self.child_pid = None
		self.child_read = None
		self.child_write = None
		self.child_set_size = None
		self.child_stop = None

		logger.info("Client connecting to terminal websocket: %s", self.request.peer)
		self._set_auth_module()
		self._getSession(None)
		try:
			self._authenticate(None)
		except Exception as err:
			logger.warning("Authentication error: %s", err)
			self.session.authenticated = False

	def send(self, data):
		try:
			self.sendMessage(data, isBinary=True)
		except Exception as err:
			logger.error("Failed to ws send: %s", err)

	def onOpen(self):
		logger.info("Terminal websocket connection opened (params: %s)", self.request.params)
		if not self.session or not self.session.authenticated:
			logger.error("No valid session supplied")
			self.sendClose(code=4401, reason="Unauthorized")
		else:
			shell = "powershell.exe" if RUNNING_ON_WINDOWS else "bash"
			lines = 30
			columns = 120
			if self.request.params.get("lines"):
				lines = int(self.request.params["lines"][0])
			if self.request.params.get("columns"):
				columns = int(self.request.params["columns"][0])
			if self.request.params.get("shell"):
				shell = self.request.params["shell"][0]

			if RUNNING_ON_WINDOWS:
				from opsiclientd.windows import start_pty
			else:
				from opsiclientd.posix import start_pty

			logger.notice("Starting terminal shell=%s, lines=%d, columns=%d", shell, lines, columns)
			try:
				(
					self.child_pid,
					self.child_read,
					self.child_write,
					self.child_set_size,
					self.child_stop,
				) = start_pty(shell=shell, lines=lines, columns=columns)
				self.terminal_reader_thread = TerminalReaderThread(self)
				self.terminal_reader_thread.start()
			except Exception as err:
				self.sendClose(code=500, reason=str(err))

	def onMessage(self, payload, isBinary):
		# logger.debug("onMessage: %s - %s", isBinary, payload)
		self.child_write(payload)

	def onClose(self, wasClean, code, reason):
		logger.info("Terminal websocket connection closed: %s", reason)
		if self.terminal_reader_thread:
			self.terminal_reader_thread.stop()
		self.child_stop()
