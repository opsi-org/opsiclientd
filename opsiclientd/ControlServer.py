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
:license: GNU Affero General Public License version 3
"""
import codecs
import os
import re
import shutil
import sys
import threading
import time

from OPSI import System
from OPSI.Backend.Backend import ConfigDataBackend
from OPSI.Exceptions import OpsiAuthenticationError
from OPSI.Logger import Logger
from OPSI.Types import forceBool, forceInt, forceUnicode

from opsiclientd.ControlPipe import OpsiclientdRpcPipeInterface
from opsiclientd.Config import Config, getLogFormat
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
logger = Logger()
state = State()

infoPage = """<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Strict//EN"
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
"""

try:
	fsencoding = sys.getfilesystemencoding()
	if not fsencoding:
		raise ValueError("getfilesystemencoding returned {!r}".format(fsencoding))
except Exception as err:
	logger.info("Problem getting filesystemencoding: {}", err)
	defaultEncoding = sys.getdefaultencoding()
	logger.notice("Patching filesystemencoding to be {!r}", defaultEncoding)
	sys.getfilesystemencoding = lambda: defaultEncoding

class ControlServer(threading.Thread):
	def __init__(self, opsiclientd, httpsPort, sslServerKeyFile, sslServerCertFile, staticDir=None):
		logger.setLogFormat(getLogFormat("control server"), object=self)
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

		logger.info("ControlServer initiated")
		self.authFailureCount = {}

	def run(self):
		self._running = True
		while self._running:
			time.sleep(1)
	
	def stop(self):
		self._running = False

class OpsiclientdRpcInterface(OpsiclientdRpcPipeInterface):
	def __init__(self, opsiclientd):
		OpsiclientdRpcPipeInterface.__init__(self, opsiclientd)

	def noop(self, arg):
		pass

	def cacheService_syncConfig(self):
		return self.opsiclientd.getCacheService().syncConfig()

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
		logger.notice(u"rpc setBlockLogin: blockLogin set to {!r}", self.opsiclientd._blockLogin)
		if self.opsiclientd._blockLogin:
			return u"Login blocker is on"
		else:
			return u"Login blocker is off"

	def readLog(self, logType='opsiclientd'):
		logType = forceUnicode(logType)
		if logType != 'opsiclientd':
			raise ValueError(u"Unknown log type '%s'" % logType)

		logger.notice(u"rpc readLog: reading log of type {!r}", logType)

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
			return ConfigDataBackend._truncateLogData(data, maxSize)

		return data

	def runCommand(self, command, sessionId=None, desktop=None):
		command = forceUnicode(command)
		if not command:
			raise ValueError("No command given")

		if sessionId:
			sessionId = forceInt(sessionId)
		else:
			sessionId = System.getActiveSessionId(self.opsiclientd._winApiBugCommand)

		if desktop:
			desktop = forceUnicode(desktop)
		else:
			desktop = self.opsiclientd.getCurrentActiveDesktopName()

		logger.notice(u"rpc runCommand: executing command {!r} in session {:d} on desktop {!r}", command, sessionId, desktop)
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
		logger.notice(u"rpc shutdown: shutting down computer in {} seconds", waitSeconds)
		System.shutdown(wait=waitSeconds)

	def reboot(self, waitSeconds=0):
		waitSeconds = forceInt(waitSeconds)
		logger.notice(u"rpc reboot: rebooting computer in {} seconds", waitSeconds)
		System.reboot(wait=waitSeconds)

	def uptime(self):
		uptime = int(time.time() - self.opsiclientd._startupTime)
		logger.notice(u"rpc uptime: opsiclientd is running for {:d} seconds", uptime)
		return uptime

	def fireEvent(self, name):
		event = getEventGenerator(name)
		logger.notice(u"Firing event '%s'" % name)
		event.createAndFireEvent()

	def setStatusMessage(self, sessionId, message):
		sessionId = forceInt(sessionId)
		message = forceUnicode(message)
		ept = self.opsiclientd.getEventProcessingThread(sessionId)
		logger.notice(u"rpc setStatusMessage: Setting status message to {0!r}", message)
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
		logger.notice(u"rpc getCurrentActiveDesktopName: current active desktop name is {0}", desktop)
		return desktop

	def setCurrentActiveDesktopName(self, sessionId, desktop):
		sessionId = forceInt(sessionId)
		desktop = forceUnicode(desktop)
		self.opsiclientd._currentActiveDesktopName[sessionId] = desktop
		logger.notice(u"rpc setCurrentActiveDesktopName: current active desktop name for session {0} set to {1!r}", sessionId, desktop)

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

		for session in System.getActiveSessionInformation(self.opsiclientd._winApiBugCommand):
			year = 0
			month = 0
			day = 0
			hour = 0
			minute = 0
			second = 0
			logger.debug(u"session to check for LogonTime {0!r}", session)

			if isinstance(session['LogonTime'], str):
				match = None
				pattern = re.compile("^(\d+)/(\d+)/(\d+)\s(\d+):(\d+):(\d+)")
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
