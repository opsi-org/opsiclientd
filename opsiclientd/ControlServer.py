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
import shlex
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib
import warnings
from collections import namedtuple
from pathlib import Path
from types import ModuleType
from typing import Union
from uuid import uuid4

import msgpack  # type: ignore[import]
import psutil  # type: ignore[import]
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from OpenSSL import SSL
from opsicommon import __version__ as opsicommon_version

with warnings.catch_warnings():
	warnings.filterwarnings("ignore", category=DeprecationWarning)
	from autobahn.twisted.resource import WebSocketResource  # type: ignore[import]
	from autobahn.twisted.websocket import (  # type: ignore[import]
		WebSocketServerFactory,
		WebSocketServerProtocol,
	)

from OPSI import System  # type: ignore[import]
from OPSI import __version__ as python_opsi_version  # type: ignore[import]
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
from OPSI.Util.Log import truncateLogData  # type: ignore[import]
from opsicommon.exceptions import OpsiServiceAuthenticationError
from opsicommon.logging import (
	LEVEL_TO_NAME,
	OPSI_LEVEL_TO_LEVEL,
	get_logger,
	log_context,
	secret_filter,
)
from opsicommon.types import forceBool, forceInt, forceProductIdList, forceUnicode
from opsicommon.utils import generate_opsi_host_key
from twisted.internet import fdesc
from twisted.internet.abstract import isIPv6Address
from twisted.internet.base import BasePort
from twisted.internet.error import CannotListenError
from twisted.web import server
from twisted.web.resource import Resource
from twisted.web.static import File

from opsiclientd import __version__
from opsiclientd.Config import OPSI_SETUP_USER_NAME, Config
from opsiclientd.ControlPipe import OpsiclientdRpcPipeInterface
from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.Events.Utilities.Generators import getEventGenerator
from opsiclientd.OpsiService import ServiceConnection, download_from_depot
from opsiclientd.SoftwareOnDemand import ResourceKioskJsonRpc
from opsiclientd.State import State
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS
from opsiclientd.Timeline import Timeline

if RUNNING_ON_WINDOWS:
	from opsiclientd.windows import runCommandInSession
else:
	from OPSI.System import runCommandInSession  # type: ignore


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
		self._opsiclientdRpcInterface = OpsiclientdRpcInterface(self._opsiclientd)

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


class OpsiclientdRpcInterface(OpsiclientdRpcPipeInterface):
	def __init__(self, opsiclientd):
		OpsiclientdRpcPipeInterface.__init__(self, opsiclientd)
		self._run_as_opsi_setup_user_lock = threading.Lock()

	def wait(self, seconds: int = 0):
		for _ in range(int(seconds)):
			time.sleep(1)

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
		cacheService.clear_product_cache()
		return "config and product cache deleted"

	def timeline_getEvents(self):
		timeline = Timeline()
		return timeline.getEvents()

	def setBlockLogin(self, blockLogin, handleNotifier=True):
		self.opsiclientd.setBlockLogin(forceBool(blockLogin), forceBool(handleNotifier))
		logger.notice("rpc setBlockLogin: blockLogin set to '%s'", self.opsiclientd._blockLogin)
		if self.opsiclientd._blockLogin:
			return "Login blocker is on"
		return "Login blocker is off"

	def readLog(self, logType="opsiclientd"):
		logType = forceUnicode(logType)
		if logType != "opsiclientd":
			raise ValueError(f"Unknown log type '{logType}'")

		logger.notice("rpc readLog: reading log of type '%s'", logType)

		if logType == "opsiclientd":
			with codecs.open(config.get("global", "log_file"), "r", "utf-8", "replace") as log:
				return log.read()

		return ""

	def log_read(self, logType="opsiclientd", extension="", maxSize=5000000):
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
		LOG_DIR = os.path.dirname(config.get("global", "log_file"))
		LOG_TYPES = [  # possible logtypes
			"opsiclientd",
			"opsi-script",
			"opsi_loginblocker",
			"opsiclientdguard",
			"notifier_block_login",
			"notifier_event",
			"opsi-client-agent",
		]
		logType = forceUnicode(logType)

		if logType not in LOG_TYPES:
			raise ValueError(f"Unknown log type {logType}")

		if extension:
			extension = forceUnicode(extension)
			logFile = os.path.join(LOG_DIR, f"{logType}.log.{extension}")
			if not os.path.exists(logFile):
				# Try the other format:
				logFile = os.path.join(LOG_DIR, f"{logType}_{extension}.log")
		else:
			logFile = os.path.join(LOG_DIR, f"{logType}.log")

		try:
			with codecs.open(logFile, "r", "utf-8", "replace") as log:
				data = log.read()
		except IOError as ioerr:
			if ioerr.errno == 2:  # This is "No such file or directory"
				return "No such file or directory"
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
		runCommandInSession(command=command, sessionId=sessionId, desktop=desktop, waitForProcessEnding=False)
		return f"command '{command}' executed"

	def execute(self, command, waitForEnding=True, captureStderr=True, encoding=None, timeout=300):
		return System.execute(cmd=command, waitForEnding=waitForEnding, captureStderr=captureStderr, encoding=encoding, timeout=timeout)

	def logoffSession(self, session_id=None, username=None):
		return System.logoffSession(session_id=session_id, username=username)

	def logoffCurrentUser(self):
		logger.notice("rpc logoffCurrentUser: logging of current user now")
		System.logoffCurrentUser()

	def lockSession(self, session_id=None, username=None):
		return System.lockSession(session_id=session_id, username=username)

	def lockWorkstation(self):
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
		uptime = int(time.time() - self.opsiclientd._startupTime)
		logger.notice("rpc uptime: opsiclientd is running for %d seconds", uptime)
		return uptime

	def fireEvent(self, name, can_cancel=True, event_info=None):
		# can_cancel: Allow event cancellation for new events called via the ControlServer
		can_cancel = forceBool(can_cancel)
		event_info = event_info or {}
		event_generator = getEventGenerator(name)
		logger.notice("rpc firing event %r, event_info=%r, can_cancel=%r", name, event_info, can_cancel)
		event_generator.createAndFireEvent(eventInfo=event_info, can_cancel=can_cancel)

	def setStatusMessage(self, sessionId, message):
		sessionId = forceInt(sessionId)
		message = forceUnicode(message)
		try:
			ept = self.opsiclientd.getEventProcessingThread(sessionId)
			logger.notice("rpc setStatusMessage: Setting status message to '%s'", message)
			ept.setStatusMessage(message)
		except LookupError as error:
			logger.warning("Session does not match EventProcessingThread: %s", error, exc_info=True)

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

	def cancelEvents(self, ids=None):
		for ept in self.opsiclientd.getEventProcessingThreads():
			if not ids or ept.event.eventConfig.getId() in ids:
				ept.cancel()
				return True
		return False

	def isInstallationPending(self):
		return forceBool(self.opsiclientd.isInstallationPending())

	def getCurrentActiveDesktopName(self, sessionId=None):
		desktop = self.opsiclientd.getCurrentActiveDesktopName(sessionId)
		logger.notice("rpc getCurrentActiveDesktopName: current active desktop name is %s", desktop)
		return desktop

	def setCurrentActiveDesktopName(self, sessionId, desktop):
		sessionId = forceInt(sessionId)
		desktop = forceUnicode(desktop)
		self.opsiclientd._currentActiveDesktopName[sessionId] = desktop
		logger.notice("rpc setCurrentActiveDesktopName: current active desktop name for session %s set to '%s'", sessionId, desktop)

	def switchDesktop(self, desktop, sessionId=None):
		self.opsiclientd.switchDesktop(desktop, sessionId)

	def getConfig(self):
		return config.getDict()

	def getConfigValue(self, section, option):
		section = forceUnicode(section)
		option = forceUnicode(option)
		return config.get(section, option)

	def setConfigValue(self, section, option, value):
		section = forceUnicode(section)
		option = forceUnicode(option)
		value = forceUnicode(value)
		return config.set(section, option, value)

	def set(self, section, option, value):
		# Legacy method
		return self.setConfigValue(section, option, value)

	def readConfigFile(self):
		config.readConfigFile()

	def updateConfigFile(self, force=False):
		config.updateConfigFile(force)

	def showPopup(self, message, mode="prepend", addTimestamp=True, displaySeconds=0):
		message = forceUnicode(message)
		self.opsiclientd.showPopup(message=message, mode=mode, addTimestamp=addTimestamp, displaySeconds=displaySeconds)

	def deleteServerCerts(self):
		cert_dir = config.get("global", "server_cert_dir")
		if os.path.exists(cert_dir):
			for filename in os.listdir(cert_dir):
				if os.path.basename(config.ca_cert_file).lower() in filename.strip().lower():
					continue
				os.remove(os.path.join(cert_dir, filename))

	def updateOpsiCaCert(self, ca_cert_pem: str) -> None:
		ca_certs: list[x509.Certificate] = []
		for match in re.finditer(r"(-+BEGIN CERTIFICATE-+.*?-+END CERTIFICATE-+)", ca_cert_pem, re.DOTALL):
			try:
				ca_certs.append(x509.load_pem_x509_certificate(match.group(1).encode("utf-8")))
			except Exception as err:
				logger.error(err, exc_info=True)

		if ca_certs:
			if not os.path.isdir(os.path.dirname(config.ca_cert_file)):
				os.makedirs(os.path.dirname(config.ca_cert_file))
			with open(config.ca_cert_file, "wb") as file:
				for cert in ca_certs:
					file.write(cert.public_bytes(encoding=serialization.Encoding.PEM))

	def getActiveSessions(self):
		sessions = System.getActiveSessionInformation()
		for session in sessions:
			session["LogonDomain"] = session.get("DomainName")
		return sessions

	def getBackendInfo(self):
		serviceConnection = ServiceConnection(self.opsiclientd)
		serviceConnection.connectConfigService()
		backendinfo = None
		try:
			configService = serviceConnection.getConfigService()
			backendinfo = configService.backend_info()
		finally:
			serviceConnection.disconnectConfigService()

		return backendinfo

	def getState(self, name, default=None):
		"""
		Return a specified state.

		:param name: Name of the state.
		:param default: Default value if something goes wrong.
		"""
		return state.get(name, default)

	def setState(self, name, value):
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

	def execPythonCode(self, code):
		"""Execute lines of python code, returns the result of the last line"""
		code = code.split("\n")
		exec("\n".join(code[:-1]))
		return eval(code[-1])

	def loginUser(self, username, password):
		try:
			secret_filter.add_secrets(password)
			return self.opsiclientd.loginUser(username, password)
		except Exception as err:
			logger.error(err, exc_info=True)
			raise

	def loginOpsiSetupUser(self, admin=True, recreate_user=False):
		for session_id in System.getUserSessionIds(OPSI_SETUP_USER_NAME):
			System.logoffSession(session_id)
		user_info = self.opsiclientd.createOpsiSetupUser(admin=admin, delete_existing=recreate_user)
		return self.opsiclientd.loginUser(user_info["name"], user_info["password"])

	def getOpenFiles(self, process_filter: str = ".*", path_filter: str = ".*"):
		re_process_filter = re.compile(process_filter, flags=re.IGNORECASE)
		re_path_filter = re.compile(path_filter, flags=re.IGNORECASE)

		file_list = set()
		for proc in psutil.process_iter():
			proc_name = proc.name()
			if not re_process_filter.match(proc_name):
				continue
			try:
				for file in proc.open_files():
					if not re_path_filter.match(file.path):
						continue
					file_list.add((file.path, proc_name))
			except Exception as err:
				logger.warning("Failed to get open files for: %s", err, exc_info=True)

		return [{"file_path": x[0], "process_name": x[1]} for x in sorted(list(file_list))]

	def runOpsiScriptAsOpsiSetupUser(
		self,
		script: str,
		product_id: str | None = None,
		admin: bool = True,
		wait_for_ending: Union[bool, int] = 7200,
		remove_user: bool = False,
	):
		if not RUNNING_ON_WINDOWS:
			raise NotImplementedError()

		if remove_user and not wait_for_ending:
			wait_for_ending = True
		if isinstance(wait_for_ending, bool) and wait_for_ending:
			wait_for_ending = 7200

		logger.notice(
			"Executing opsi script '%s' as opsisetupuser (product_id=%s, admin=%s, wait_for_ending=%s, remove_user=%s)",
			script,
			product_id,
			admin,
			wait_for_ending,
			remove_user,
		)

		serviceConnection = ServiceConnection(self.opsiclientd)
		serviceConnection.connectConfigService()
		try:
			configServiceUrl = serviceConnection.getConfigServiceUrl()
			config.selectDepotserver(
				configService=serviceConnection.getConfigService(),
				mode="mount",
				productIds=[product_id] if product_id else None,
			)
			depot_server_username, depot_server_password = config.getDepotserverCredentials(
				configService=serviceConnection.getConfigService()
			)

			depot_server_url = config.get("depot_server", "url")
			if not depot_server_url:
				raise RuntimeError("depot_server.url not defined")
			depot_path = config.get_depot_path()
			depot_drive = config.getDepotDrive()
			if depot_path == depot_drive:
				# Prefer depot drive if not in use
				depot_path = depot_drive = System.get_available_drive_letter(start=depot_drive.rstrip(":")).rstrip(":") + ":"

			if not os.path.isabs(script):
				script = os.path.join(depot_path, os.sep, script)

			log_file = os.path.join(config.get("global", "log_dir"), "opsisetupuser.log")

			command = os.path.join(config.get("action_processor", "local_dir"), config.get("action_processor", "filename"))
			if product_id:
				product_id = f'/productid \\"{product_id}\\" '
			else:
				product_id = ""

			command = (
				f'\\"{command}\\" \\"{script}\\" \\"{log_file}\\" /servicebatch {product_id}'
				f'/opsiservice \\"{configServiceUrl}\\" '
				f'/clientid \\"{config.get("global", "host_id")}\\" '
				f'/username \\"{config.get("global", "host_id")}\\" '
				f'/password \\"{config.get("global", "opsi_host_key")}\\"'
			)

			ps_script = Path(config.get("global", "tmp_dir")) / f"run_as_opsi_setup_user_{uuid4()}.ps1"

			ps_script.write_text(
				(
					f"$args = @("
					f"'{config.get('global', 'host_id')}',"
					f"'{config.get('global', 'opsi_host_key')}',"
					f"'{config.get('control_server', 'port')}',"
					f"'{config.get('global', 'log_file')}',"
					f"'{config.get('global', 'log_level')}',"
					f"'{depot_server_url}',"
					f"'{depot_drive}',"
					f"'{depot_server_username}',"
					f"'{depot_server_password}',"
					f"'-1',"
					f"'default',"
					f"'{command}',"
					f"'3600',"
					f"'{OPSI_SETUP_USER_NAME}',"
					f"'\"\"',"
					f"'false'"
					f")\r\n"
					f'& "{os.path.join(os.path.dirname(sys.argv[0]), "action_processor_starter.exe")}" $args\r\n'
					f'Remove-Item -Path "{str(ps_script)}" -Force\r\n'
				),
				encoding="windows-1252",
			)

			self._run_powershell_script_as_opsi_setup_user(
				script=ps_script,
				admin=admin,
				recreate_user=False,
				remove_user=remove_user,
				wait_for_ending=wait_for_ending,
				shell_window_style="hidden",
			)
		finally:
			logger.info("Finished runOpsiScriptAsOpsiSetupUser - disconnecting ConfigService")
			serviceConnection.disconnectConfigService()

	def runAsOpsiSetupUser(
		self,
		command: str = "powershell.exe -ExecutionPolicy Bypass",
		admin: bool = True,
		recreate_user: bool = False,
		remove_user: bool = False,
		wait_for_ending: Union[bool, int] = False,
	):
		script = Path(config.get("global", "tmp_dir")) / f"run_as_opsi_setup_user_{uuid4()}.ps1"
		# catch <Drive>:.....exe and put in quotes if not already quoted
		if re.search("[A-Z]:.*\\.exe", command) and not command.startswith(('"', "'")):
			command = re.sub("([A-Z]:.*\\.exe)", '"\\1"', command, count=1)
		parts = shlex.split(command, posix=False)
		if not parts:
			raise ValueError(f"Invalid command {command}")
		if len(parts) == 1:
			script_content = f"Start-Process -FilePath {parts[0]} -Wait\r\n"
		else:
			script_content = (
				f"""Start-Process -FilePath {parts[0]} -ArgumentList {','.join((f'"{entry}"' for entry in parts[1:]))} -Wait\r\n"""
			)
		# WARNING: This part is not executed if the command call above initiates reboot
		script_content += f'Remove-Item -Path "{str(script)}" -Force\r\n'
		script.write_text(script_content, encoding="windows-1252")
		logger.debug("Preparing script:\n%s", script_content)
		try:
			self._run_powershell_script_as_opsi_setup_user(
				script=script,
				admin=admin,
				recreate_user=recreate_user,
				remove_user=remove_user,
				wait_for_ending=wait_for_ending,
				shell_window_style="normal",
			)
		except Exception as err:
			logger.error(err, exc_info=True)
			raise

	def _run_process_as_opsi_setup_user(self, command: str, admin: bool, recreate_user: bool) -> None:
		# https://bugs.python.org/file46988/issue.py
		if not RUNNING_ON_WINDOWS:
			raise NotImplementedError(f"Not implemented on {platform.system()}")
		import winreg  # type: ignore[import]

		import pywintypes  # type: ignore[import]
		import win32profile  # type: ignore[import]
		import win32security  # type: ignore[import]

		for session_id in System.getUserSessionIds(OPSI_SETUP_USER_NAME):
			System.logoffSession(session_id)
		user_info = self.opsiclientd.createOpsiSetupUser(admin=admin, delete_existing=recreate_user)  # type: ignore[attr-defined]

		logon = win32security.LogonUser(
			user_info["name"],
			None,
			user_info["password"],
			win32security.LOGON32_LOGON_INTERACTIVE,
			win32security.LOGON32_PROVIDER_DEFAULT,
		)

		try:
			for attempt in (1, 2, 3, 4, 5):
				try:
					# This will create the user home dir and ntuser.dat gets loaded
					# Can fail if C:\users\default\ntuser.dat is locked by an other process
					hkey = win32profile.LoadUserProfile(logon, {"UserName": user_info["name"]})  # type: ignore[arg-type]
					break
				except pywintypes.error as err:
					logger.warning("Failed to load user profile (attempt #%d): %s", attempt, err)
					time.sleep(5)
					if attempt == 5:
						raise

			try:
				# env = win32profile.CreateEnvironmentBlock(logon, False)
				str_sid = win32security.ConvertSidToStringSid(user_info["user_sid"])
				reg_key = winreg.OpenKey(  # type: ignore[attr-defined]
					winreg.HKEY_USERS,  # type: ignore[attr-defined]
					str_sid + r"\Software\Microsoft\Windows NT\CurrentVersion\Winlogon",
					0,
					winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY,  # type: ignore[attr-defined]
				)
				with reg_key:
					winreg.SetValueEx(reg_key, "Shell", 0, winreg.REG_SZ, command)  # type: ignore[attr-defined]
			finally:
				win32profile.UnloadUserProfile(logon, hkey)  # type: ignore[arg-type]

		finally:
			logon.close()

		assert self.opsiclientd._controlPipe, "Control pipe not initialized"
		if not self.opsiclientd._controlPipe.credentialProviderConnected():  # type: ignore[attr-defined]
			for _unused in range(20):
				if self.opsiclientd._controlPipe.credentialProviderConnected():  # type: ignore[attr-defined]
					break
				time.sleep(0.5)

		self.opsiclientd.loginUser(user_info["name"], user_info["password"])

	def _run_powershell_script_as_opsi_setup_user(
		self,
		script: Path,
		admin: bool = True,
		recreate_user: bool = False,
		remove_user: bool = False,
		wait_for_ending: Union[bool, int] = False,
		shell_window_style: str = "normal",  # Normal / Minimized / Maximized / Hidden
	):
		if shell_window_style.lower() not in ("normal", "minimized", "maximized", "hidden"):
			raise ValueError(f"Invalid value for shell_window_style: {shell_window_style!r}")
		if not self._run_as_opsi_setup_user_lock.acquire(blocking=False):
			raise RuntimeError("Another process is already running")
		if remove_user and not wait_for_ending:
			wait_for_ending = True

		# Remove inherited permissions, allow SYSTEM only
		logger.info("Setting permissions: %s", ["icacls", str(script), " /inheritance:r", "/grant:r", "SYSTEM:(OI)(CI)F"])
		subprocess.run(["icacls", str(script), " /inheritance:r", "/grant:r", "SYSTEM:(OI)(CI)F"], check=False)

		try:
			self._run_process_as_opsi_setup_user(
				f'powershell.exe -ExecutionPolicy Bypass -WindowStyle {shell_window_style} -File "{str(script)}"',
				admin,
				recreate_user,
			)
			if wait_for_ending:
				timeout = 3600
				if isinstance(wait_for_ending, int):
					timeout = wait_for_ending
				logger.info("Wait for process to complete (timeout=%r)", timeout)
				try:
					start = time.time()
					while script.exists():
						time.sleep(1)
						if time.time() >= start + timeout:
							logger.warning("Timed out after %r seconds while waiting for process to complete", timeout)
							break
				finally:
					for session_id in System.getUserSessionIds(OPSI_SETUP_USER_NAME):
						System.logoffSession(session_id)
					if script.exists():
						script.unlink()
					if remove_user:
						self.opsiclientd.cleanup_opsi_setup_user()  # type: ignore[attr-defined]
		except Exception as err:
			logger.error(err, exc_info=True)
			raise
		finally:
			self._run_as_opsi_setup_user_lock.release()

	def removeOpsiSetupUser(self):
		self.opsiclientd.cleanup_opsi_setup_user()

	def runOnShutdown(self):
		on_shutdown_active = False
		for event_config in getEventConfigs().values():
			if event_config["name"] == "on_shutdown" and event_config["active"]:
				on_shutdown_active = True
				break

		if not on_shutdown_active:
			logger.info("on_shutdown event is not active")
			return False

		if self.opsiclientd.isRebootTriggered() or self.opsiclientd.isShutdownTriggered():
			logger.info("Reboot or shutdown is triggered, not firing on_shutdown")
			return False

		if self.isInstallationPending():
			logger.info("Installations are pending, not firing on_shutdown")
			return False

		logger.info("Firing on_shutdown and waiting for event to complete")
		self.fireEvent("on_shutdown")
		time.sleep(10)
		while self.isEventRunning("on_shutdown"):
			time.sleep(10)

		logger.info("on_shutdown event completed")
		return True

	def messageOfTheDayUpdated(
		self,
		device_message: str | None = None,
		device_message_valid_until: int = 0,
		user_message: str | None = None,
		user_message_valid_until: int = 0,
	) -> list[str]:
		return self.opsiclientd.updateMOTD(
			device_message=device_message,
			device_message_valid_until=device_message_valid_until,
			user_message=user_message,
			user_message_valid_until=user_message_valid_until,
		)

	def processActionRequests(self, product_ids=None):
		event = config.get("control_server", "process_actions_event")
		if not event or event == "auto":
			timer_active = False
			on_demand_active = False
			for event_config in getEventConfigs().values():
				if event_config["name"] == "timer" and event_config["active"]:
					timer_active = True
				elif event_config["name"] == "on_demand" and event_config["active"]:
					on_demand_active = True

			if timer_active:
				event = "timer"
			elif on_demand_active:
				event = "on_demand"
			else:
				raise RuntimeError("Neither timer nor on_demand event active")

		event_info = {}
		if product_ids:
			event_info = {"product_ids": forceProductIdList(product_ids)}
		self.fireEvent(name=event, event_info=event_info)

	def getConfigDataFromOpsiclientd(self, get_depot_id=True, get_active_events=True):
		result = {}
		result["opsiclientd_version"] = (
			f"Opsiclientd {__version__} [python-opsi={python_opsi_version}python-opsi-common={opsicommon_version}]"
		)

		if get_depot_id:
			result["depot_id"] = config.get("depot_server", "master_depot_id")

		if get_active_events:
			active_events = []
			for event_config in getEventConfigs().values():
				if event_config["active"]:
					active_events.append(event_config["name"])

			result["active_events"] = list(set(active_events))
		return result

	def downloadFromDepot(self, product_id: str, destination: str, sub_path: str | None = None):
		return download_from_depot(product_id, Path(destination).resolve(), sub_path)

	def getLogs(self, log_types: list[str] | None = None, max_age_days: int = 0) -> str:
		file_path = self.opsiclientd.collectLogfiles(types=log_types, max_age_days=max_age_days)
		assert self.opsiclientd._permanent_service_connection, "Need permanent service connection for getLogs"
		logger.notice("Delivering file %s", file_path)
		with open(file_path, "rb") as file_handle:
			# requests accepts "Dictionary, list of tuples, bytes, or file-like object to send in the body of the Request" as data
			response = self.opsiclientd._permanent_service_connection.service_client.post("/file-transfer", data=file_handle)  # type: ignore[call-overload]
			logger.debug("Got response with status %s: %s", response.status_code, response.content.decode("utf-8"))
			return json.loads(response.content.decode("utf-8"))

	def replaceOpsiHostKey(self, new_key: str | None = None):
		if not new_key:
			new_key = generate_opsi_host_key()
		secret_filter.add_secrets(new_key)

		logger.info("Replacing opsi host key on service")
		serviceConnection = ServiceConnection(self.opsiclientd)
		serviceConnection.connectConfigService()
		try:
			configService = serviceConnection.getConfigService()
			host = configService.host_getObjects(id=config.get("global", "host_id"))[0]
			host.setOpsiHostKey(new_key)
			configService.host_updateObject(host)
		finally:
			serviceConnection.disconnectConfigService()

		logger.info("Replacing opsi host key in config")
		config.set("global", "opsi_host_key", new_key)
		config.updateConfigFile(force=True)

		logger.info("Removing config cache")
		try:
			cache_service = self.opsiclientd.getCacheService()
			cache_service.setConfigCacheFaulty()
			cache_service._configCacheService.delete_cache_dir()
		except Exception as err:
			logger.warning(err, exc_info=True)

		self.opsiclientd.restart(2)

	def getProcessInfo(self, interval=5.0):
		info = {"threads": []}
		proc = psutil.Process()
		proc.cpu_percent()
		cpu_times_start = proc.cpu_times()._asdict()
		p_thread_cpu_times_start = {t.id: {"user": t.user_time, "system": t.system_time} for t in proc.threads()}
		time.sleep(interval)
		cpu_percent = proc.cpu_percent()
		cpu_times_end = proc.cpu_times()._asdict()
		cpu_times = {k: v - cpu_times_start[k] for k, v in cpu_times_end.items()}
		info["cpu_times"] = cpu_times
		info["cpu_percent"] = cpu_percent
		cpu_times_proc = cpu_times["system"] + cpu_times["user"]
		thread_by_id = {t.native_id: t for t in threading.enumerate()}
		for p_thread in proc.threads():
			thread = thread_by_id.get(p_thread.id)
			if not thread:
				continue
			cts = p_thread_cpu_times_start.get(p_thread.id)
			user_time = p_thread.user_time - cts["user"]
			system_time = p_thread.system_time - cts["system"]
			info["threads"].append(
				{
					"id": p_thread.id,
					"name": thread.name,
					"run_func": str(thread.run),
					"cpu_times": {"user": user_time, "system": system_time},
					"cpu_percent": (cpu_percent * ((system_time + user_time) / cpu_times_proc)) if cpu_times_proc else 0.0,
				}
			)
		return info
