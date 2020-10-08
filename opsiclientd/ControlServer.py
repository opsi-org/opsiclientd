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
Server component for controlling opsiclientd.

These classes are used to create a https service which executes remote
procedure calls

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:license: GNU Affero General Public License version 3
"""
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
import subprocess

from twisted.internet import reactor
from twisted.internet.error import CannotListenError
from twisted.web.static import File
from twisted.web import resource, server, http, http_headers

from OPSI import System
from OPSI.Util.Log import truncateLogData
from OPSI.Backend.Backend import ConfigDataBackend
from OPSI.Exceptions import OpsiAuthenticationError
import opsicommon.logging
from opsicommon.logging import logger
from OPSI.Service import SSLContext, OpsiService
from OPSI.Service.Worker import WorkerOpsi, WorkerOpsiJsonRpc, WorkerOpsiJsonInterface
from OPSI.Service.Resource import ResourceOpsi, ResourceOpsiJsonRpc, ResourceOpsiJsonInterface
from OPSI.Types import forceBool, forceInt, forceUnicode

from opsiclientd.ControlPipe import OpsiclientdRpcPipeInterface
from opsiclientd.Config import Config
from opsiclientd.Events.Utilities.Generators import getEventGenerator
from opsiclientd.OpsiService import ServiceConnection
from opsiclientd.State import State
from opsiclientd.SoftwareOnDemand import ResourceKioskJsonRpc
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS
from opsiclientd.Timeline import Timeline

if RUNNING_ON_WINDOWS:
	import win32net
	import win32security

config = Config()
state = State()

infoPage = u'''<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
"http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd">

<html xmlns="http://www.w3.org/1999/xhtml">
<head>
	<meta http-equiv="Content-Type" content="text/xhtml; charset=utf-8" />
	<title>%(hostname)s opsi client daemon info</title>
	<link rel="stylesheet" type="text/css" href="/opsiclientd.css" />
	%(head)s
	<script type="text/javascript">
	// <![CDATA[
	function onPageLoad(){
		onLoad();
		//var logDiv = document.getElementById("infopage-opsiclientd-log");
		//logDiv.scrollTop = logDiv.scrollHeight;
	}
	// ]]>
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

try:
	fsencoding = sys.getfilesystemencoding()
	if not fsencoding:
		raise ValueError("getfilesystemencoding returned {!r}".format(fsencoding))
except Exception as err:
	logger.info("Problem getting filesystemencoding: %s", err)
	defaultEncoding = sys.getdefaultencoding()
	logger.notice("Patching filesystemencoding to be '%s'", defaultEncoding)
	sys.getfilesystemencoding = lambda: defaultEncoding


class WorkerOpsiclientd(WorkerOpsi):
	def __init__(self, service, request, resource):
		WorkerOpsi.__init__(self, service, request, resource)
		self._auth_module = None
		if os.name == 'posix':
			import OPSI.Backend.Manager.Authentication.PAM
			self._auth_module = OPSI.Backend.Manager.Authentication.PAM.PAMAuthentication()
		elif os.name == 'nt':
			import OPSI.Backend.Manager.Authentication.NT
			self._auth_module = OPSI.Backend.Manager.Authentication.NT.NTAuthentication("S-1-5-32-544")

	def run(self):
		with opsicommon.logging.log_context({'instance' : 'control server'}):
			super().run()
	
	def _getCredentials(self):
		(user, password) = self._getAuthorization()

		if not user:
			user = config.get('global', 'host_id')

		return (user, password)

	def _errback(self, failure):
		result = WorkerOpsi._errback(self, failure)
		logger.debug(u"DEBUG: detected host: '%s'", self.request.getClientIP())
		logger.debug(u"DEBUG: responsecode: '%s'", self.request.code)
		logger.debug(u"DEBUG: maxAuthenticationFailures config: '%s'", config.get('control_server', 'max_authentication_failures'))
		logger.debug(u"DEBUG: maxAuthenticationFailures config type: '%s'", type(config.get('control_server', 'max_authentication_failures')))

		if self.request.code == 401 and self.request.getClientIP() != "127.0.0.1":
			maxAuthenticationFailures = config.get('control_server', 'max_authentication_failures')
			if maxAuthenticationFailures > 0:
				try:
					self.service.authFailureCount[self.request.getClientIP()] += 1
				except KeyError:
					self.service.authFailureCount[self.request.getClientIP()] = 1

				if self.service.authFailureCount[self.request.getClientIP()] > maxAuthenticationFailures:
					logger.error(
						u"%s authentication failures from '%s' in a row, waiting 60 seconds to prevent flooding",
						self.service.authFailureCount[self.request.getClientIP()],
						self.request.getClientIP()
					)

					return self._delayResult(60, result)
		return result

	"""
	def _authenticate_windows_user(self, result):
		user_is_admin = False
		# The LogonUser function will raise an Exception on logon failure
		win32security.LogonUser(self.session.user, 'None', self.session.password, win32security.LOGON32_LOGON_NETWORK, win32security.LOGON32_PROVIDER_DEFAULT)
		# No exception raised => user authenticated
		
		# Get local admin group by sid and test if authorizing user is member of this group
		admingroupsid = "S-1-5-32-544"
		group_resume = 1
		while group_resume:
			group_resume = 0
			data, total, group_resume = win32net.NetLocalGroupEnum(None, 1, group_resume)
			for group in data:
				groupname = group.get("name")
				if not groupname:
					continue
				pysid, string, integer = win32security.LookupAccountName(None, groupname)
				if admingroupsid in str(pysid):
					member_resume = 1
					while member_resume:
						member_resume = 0
						memberdata, total, member_resume = win32net.NetLocalGroupGetMembers(None, groupname, 2, member_resume)
						logger.notice(memberdata)
						for member in memberdata:
							member_sid = member.get("sid")
							if not member_sid:
								continue
							username, domain, type = win32security.LookupAccountSid(None, member_sid)
							if self.session.user.lower() == username.lower():
								user_is_admin = True
								group_resume = 0
								member_resume = 0
								break
		
		#if self.session.user.lower() == 'administrator':
		#	user_is_admin = True
		
		if not user_is_admin:
			raise Exception("Not an admin user")
	"""

	def _authenticate(self, result):
		if self.session.authenticated:
			return result

		try:
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
				logger.info("Authentication successful for user '%s', groups '%s' (admin group: %s)" % \
					(self.session.user, ','.join(self._auth_module.get_groupnames(self.session.user)), self._auth_module.get_admin_groupname())
				)
				if not self._auth_module.user_is_admin(self.session.user):
					raise Exception("Not an admin user")
			else:
				raise Exception("Invalid credentials")
		except Exception as e:
			raise OpsiAuthenticationError("Forbidden: %s" % forceUnicode(e))
		
		# Auth ok
		try:
			del self.service.authFailureCount[self.request.getClientIP()]
		except KeyError:
			pass
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


class WorkerOpsiclientdJsonInterface(WorkerOpsiclientdJsonRpc, WorkerOpsiJsonInterface):
	def __init__(self, service, request, resource):
		WorkerOpsiclientdJsonRpc.__init__(self, service, request, resource)
		WorkerOpsiJsonInterface.__init__(self, service, request, resource)
		self.path = u'interface'

	def _getCallInstance(self, result):
		return WorkerOpsiclientdJsonRpc._getCallInstance(self, result)

	def _generateResponse(self, result):
		return WorkerOpsiJsonInterface._generateResponse(self, result)


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
			raise Exception(u'Cache service not running')

		self.session.callInstance = self.service._opsiclientd.getCacheService().getConfigBackend()
		logger.notice(u'Backend created: %s' % self.session.callInstance)
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
		self.path = u'rpcinterface'

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
			html = infoPage % {
				"head": timeline.getHtmlHead(),
				"hostname": config.get("global", "host_id"),
			}
			self.request.setHeader("content-type", "text/html; charset=utf-8")
			self.request.write(html.encode("utf-8").strip())


class WorkerOpsiclientdUpload(WorkerOpsiclientd):
	def __init__(self, service, request, resource):
		WorkerOpsiclientd.__init__(self, service, request, resource)
	
	def self_update(self):
		test_file = "base_library.zip"
		inst_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
		if not os.path.exists(os.path.join(inst_dir, test_file)):
			raise RuntimeError(f"File not found: {os.path.join(inst_dir, test_file)}")
		
		filename = None
		file_data = self.request.content.read()
		if self.request.getHeader("Content-Type") == "multipart/form-data":
			headers = b""
			for k, v in self.request.requestHeaders.getAllRawHeaders():
				headers += k + b": " + v[0] + b"\r\n"
			
			msg = email.message_from_bytes(headers + b"\r\n\r\n" + file_data)
			fpart = None
			if msg.is_multipart():
				for part in msg.walk():
					if part.get_filename():
						filename = part.get_filename()
						file_data = fpart.get_payload(decode=True)
						break
		else:
			filename = self.request.getHeader("Content-Disposition")
			if filename:
				filename = filename.split(';')[0].split('=', 1)[1]
		
		if filename:
			filename = filename.split("/")[-1].split("\\")[-1]
		
		if not filename:
			raise RuntimeError("Filename missing")
		
		logger.info("Processing file %s", filename)
		with tempfile.TemporaryDirectory() as tmpdir:
			tmpfile = os.path.join(tmpdir, filename)
			with open(tmpfile, "wb") as f:
				f.write(file_data)
			
			destination = os.path.join(tmpdir, "content")
			shutil.unpack_archive(filename=tmpfile, extract_dir=destination)
			
			bin_dir = destination
			if not os.path.exists(os.path.join(bin_dir, test_file)):
				bin_dir = None
				for fn in os.listdir(destination):
					if os.path.exists(os.path.join(destination, fn, test_file)):
						bin_dir = os.path.join(destination, fn)
						break
			if not bin_dir:
				raise RuntimeError("Invalid archive")
			
			binary = os.path.join(bin_dir, os.path.basename(sys.argv[0]))
			logger.info("Testing new binary: %s", binary)
			out = subprocess.check_output([binary, "--version"])
			logger.info(out)
			
			move_dir = inst_dir + "_old"
			logger.info("Moving current installation dir '%s' to '%s'", inst_dir, move_dir)
			if os.path.exists(move_dir):
				shutil.rmtree(move_dir)
			os.rename(inst_dir, move_dir)

			if False:
				try:
					shutil.rmtree(move_dir)
				except Exception as move_error:
					logger.info("Failed to remove %s: %s", move_dir, move_error)
			logger.info("Installing '%s' into '%s'", bin_dir, inst_dir)
			shutil.copytree(bin_dir, inst_dir)
			#os.rename(bin_dir, inst_dir)

			self.service._opsiclientd.restart(5)
	
	def _getQuery(self, result):
		pass
	
	def _processQuery(self, result):
		path = urllib.parse.unquote(self.request.path.decode("utf-8"))
		if path.startswith("/upload/update/opsiclientd"):
			try:
				self.self_update()
			except Exception as e:
				logger.error(e, exc_info=True)
				raise
		else:
			raise ValueError("Invalid path")

	def _generateResponse(self, result):
		self.request.setResponseCode(200)
		self.request.setHeader("content-type", "text/plain; charset=utf-8")
		self.request.write("ok".encode("utf-8"))


class ResourceRoot(resource.Resource):
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

class ResourceOpsiclientdUpload(ResourceOpsiclientd):
	WorkerClass = WorkerOpsiclientdUpload


class ControlServer(OpsiService, threading.Thread):
	def __init__(self, opsiclientd, httpsPort, sslServerKeyFile, sslServerCertFile, staticDir=None):
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
		self._opsiclientdRpcInterface = OpsiclientdRpcInterface(self._opsiclientd)

		logger.info(u"ControlServer initiated")
		self.authFailureCount = {}

	def run(self):
		with opsicommon.logging.log_context({'instance' : 'control server'}):
			self._running = True
			try:
				logger.info(u"creating root resource")
				self.createRoot()
				self._site = server.Site(self._root)

				logger.debug('Creating SSLContext with the following values:')
				logger.debug('\t-SSL Server Key File: {path}'.format(path=self._sslServerKeyFile))
				if not os.path.exists(self._sslServerKeyFile):
					logger.warning('The SSL server key file "{path}" is missing. '
									'Please check your configuration.'.format(
										path=self._sslServerKeyFile
									)
					)
				logger.debug('\t-SSL Server Cert File: {path}'.format(path=self._sslServerCertFile))
				if not os.path.exists(self._sslServerCertFile):
					logger.warning('The SSL server certificate file "{path}" is '
									'missing. Please check your '
									'configuration.'.format(
										path=self._sslServerCertFile
									)
					)

				self._server = reactor.listenSSL(
					self._httpsPort,
					self._site,
					SSLContext(self._sslServerKeyFile, self._sslServerCertFile)
				)
				logger.notice(u"Control server is accepting HTTPS requests on port %d" % self._httpsPort)

				if not reactor.running:
					logger.debug("Reactor is not running. Starting.")
					reactor.run(installSignalHandlers=0)
					logger.debug("Reactor run ended.")
				else:
					logger.debug("Reactor already running.")
			
			except CannotListenError as err:
				logger.critical("Failed to listen on port %s: %s", self._httpsPort, err, exc_info=True)
				self._opsiclientd.stop()
			except Exception as err:
				logger.error("ControlServer error: %s", err, exc_info=True)
			finally:
				logger.notice("Control server exiting")
				self._running = False

	def stop(self):
		if self._server:
			self._server.stopListening()
		if self._sessionHandler:
			self._sessionHandler.deleteAllSessions()
		reactor.fireSystemEvent('shutdown')
		reactor.disconnectAll()
		self._running = False

	def createRoot(self):
		if self._staticDir:
			if os.path.isdir(self._staticDir):
				self._root = File(self._staticDir.encode())
			else:
				logger.error(u"Cannot add static content '/': directory '%s' does not exist.", self._staticDir)

		if not self._root:
			self._root = ResourceRoot()
		
		self._root.putChild(b"opsiclientd", ResourceOpsiclientdJsonRpc(self))
		self._root.putChild(b"interface", ResourceOpsiclientdJsonInterface(self))
		self._root.putChild(b"rpc", ResourceCacheServiceJsonRpc(self))
		self._root.putChild(b"rpcinterface", ResourceCacheServiceJsonInterface(self))
		self._root.putChild(b"info.html", ResourceOpsiclientdInfo(self))
		self._root.putChild(b"kiosk", ResourceKioskJsonRpc(self))
		self._root.putChild(b"upload", ResourceOpsiclientdUpload(self))

	def __repr__(self):
		return (
			'<ControlServer(opsiclientd={opsiclientd}, httpsPort={port}, '
			'sslServerKeyFile={keyFile}, sslServerCertFile={certFile}, '
			'staticDir={staticDir})>'.format(
				opsiclientd=self._opsiclientd,
				port=self._httpsPort,
				keyFile=self._sslServerKeyFile,
				certFile=self._sslServerCertFile,
				staticDir=self._staticDir
			)
		)


class OpsiclientdRpcInterface(OpsiclientdRpcPipeInterface):
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

		return u"product cache deleted."

	def timeline_getEvents(self):
		timeline = Timeline()
		return timeline.getEvents()

	def setBlockLogin(self, blockLogin):
		self.opsiclientd.setBlockLogin(forceBool(blockLogin))
		logger.notice(u"rpc setBlockLogin: blockLogin set to '%s'", self.opsiclientd._blockLogin)
		if self.opsiclientd._blockLogin:
			return u"Login blocker is on"
		else:
			return u"Login blocker is off"

	def readLog(self, logType='opsiclientd'):
		logType = forceUnicode(logType)
		if logType != 'opsiclientd':
			raise ValueError(u"Unknown log type '%s'" % logType)

		logger.notice(u"rpc readLog: reading log of type '%s'", logType)

		if logType == 'opsiclientd':
			with codecs.open(config.get('global', 'log_file'), 'r', 'utf-8', 'replace') as log:
				return log.read()

		return u""

	def log_read(self, logType='opsiclientd', extension='', maxSize=5000000):
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
			raise ValueError(u'Unknown log type {0!r}'.format(logType))

		if extension:
			extension = forceUnicode(extension)
			logFile = os.path.join(LOG_DIR, '{0}.log.{1}'.format(logType, extension))
			if not os.path.exists(logFile):
				# Try the other format:
				logFile = os.path.join(LOG_DIR, '{0}_{1}.log'.format(logType, extension))
		else:
			logFile = os.path.join(LOG_DIR, '{0}.log'.format(logType))

		try:
			with codecs.open(logFile, 'r', 'utf-8', 'replace') as log:
				data = log.read()
		except IOError as ioerr:
			if ioerr.errno == 2:  # This is "No such file or directory"
				return u'No such file or directory'

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

		if desktop:
			desktop = forceUnicode(desktop)
		else:
			desktop = self.opsiclientd.getCurrentActiveDesktopName()

		logger.notice(u"rpc runCommand: executing command '%s' in session %d on desktop '%s'", command, sessionId, desktop)
		System.runCommandInSession(
			command=command,
			sessionId=sessionId,
			desktop=desktop,
			waitForProcessEnding=False
		)
		return u"command '%s' executed" % command

	def execute(self, command, waitForEnding=True, captureStderr=True, encoding=None, timeout=300):
		return System.execute(
			cmd=command,
			waitForEnding=waitForEnding,
			captureStderr=captureStderr,
			encoding=encoding,
			timeout=timeout
		)

	def logoffCurrentUser(self):
		logger.notice(u"rpc logoffCurrentUser: logging of current user now")
		System.logoffCurrentUser()

	def lockWorkstation(self):
		logger.notice(u"rpc lockWorkstation: locking workstation now")
		System.lockWorkstation()

	def shutdown(self, waitSeconds=0):
		waitSeconds = forceInt(waitSeconds)
		logger.notice(u"rpc shutdown: shutting down computer in %s seconds", waitSeconds)
		self.opsiclientd.shutdownMachine(waitSeconds)

	def reboot(self, waitSeconds=0):
		waitSeconds = forceInt(waitSeconds)
		logger.notice(u"rpc reboot: rebooting computer in %s seconds", waitSeconds)
		self.opsiclientd.rebootMachine(waitSeconds)
	
	def uptime(self):
		uptime = int(time.time() - self.opsiclientd._startupTime)
		logger.notice(u"rpc uptime: opsiclientd is running for %d seconds", uptime)
		return uptime

	def fireEvent(self, name):
		event = getEventGenerator(name)
		logger.notice(u"Firing event '%s'" % name)
		event.createAndFireEvent()

	def setStatusMessage(self, sessionId, message):
		sessionId = forceInt(sessionId)
		message = forceUnicode(message)
		ept = self.opsiclientd.getEventProcessingThread(sessionId)
		logger.notice(u"rpc setStatusMessage: Setting status message to '%s'", message)
		ept.setStatusMessage(message)

	def isEventRunning(self, name):
		running = False
		for ept in self.opsiclientd._eventProcessingThreads:
			if ept.event.eventConfig.getId() == name:
				running = True
				break
		return running

	def getRunningEvents(self):
		"""
		Returns a list with running events.

		"""
		running = [ept.event.eventConfig.getId() for ept in self.opsiclientd._eventProcessingThreads]
		if not running:
			logger.info("Currently no Event is running.")
		return running

	def isInstallationPending(self):
		return forceBool(self.opsiclientd.isInstallationPending())

	def getCurrentActiveDesktopName(self, sessionId=None):
		desktop = self.opsiclientd.getCurrentActiveDesktopName(sessionId)
		logger.notice(u"rpc getCurrentActiveDesktopName: current active desktop name is %s", desktop)
		return desktop

	def setCurrentActiveDesktopName(self, sessionId, desktop):
		sessionId = forceInt(sessionId)
		desktop = forceUnicode(desktop)
		self.opsiclientd._currentActiveDesktopName[sessionId] = desktop
		logger.notice(u"rpc setCurrentActiveDesktopName: current active desktop name for session %s set to '%s'", sessionId, desktop)

	def switchDesktop(self, desktop, sessionId=None):
		self.opsiclientd.switchDesktop(desktop, sessionId)

	def set(self, section, option, value):
		section = forceUnicode(section)
		option = forceUnicode(option)
		value = forceUnicode(value)
		return config.set(section, option, value)

	def updateConfigFile(self):
		config.updateConfigFile()

	def showPopup(self, message):
		message = forceUnicode(message)
		self.opsiclientd.showPopup(message)

	def deleteServerCerts(self):
		certDir = config.get('global', 'server_cert_dir')
		if os.path.exists(certDir):
			for filename in os.listdir(certDir):
				if "cacert.pem" in filename.strip().lower():
					continue

				os.remove(os.path.join(certDir, filename))

	def getActiveSessions(self):
		sessions = []

		for session in System.getActiveSessionInformation():
			year = 0
			month = 0
			day = 0
			hour = 0
			minute = 0
			second = 0
			logger.debug(u"session to check for LogonTime '%s'", session)

			if isinstance(session['LogonTime'], str):
				match = None
				pattern = re.compile(r"^(\d+)/(\d+)/(\d+)\s(\d+):(\d+):(\d+)")
				match = pattern.match(session['LogonTime'])
				if match:
					year = match.group(3)
					month = match.group(1)
					day = match.group(2)
					hour = match.group(4)
					minute = match.group(5)
					second = match.group(6)
			else:
				year = session['LogonTime'].year
				month = session['LogonTime'].month
				day = session['LogonTime'].day
				hour = session['LogonTime'].hour
				minute = session['LogonTime'].minute
				second = session['LogonTime'].second

			if month < 10:
				month = '0%d' % month
			if day < 10:
				day = '0%d' % day
			if hour < 10:
				hour = '0%d' % hour
			if minute < 10:
				minute = '0%d' % minute
			if second < 10:
				second = '0%d' % second
			session['LogonTime'] = u'%s-%s-%s %s:%s:%s' % (year, month, day, hour, minute, second)
			session['Sid'] = str(session['Sid']).replace(u'PySID:', u'')
			sessions.append(session)

		return sessions

	def getBackendInfo(self):
		serviceConnection = ServiceConnection(loadBalance=False)
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
