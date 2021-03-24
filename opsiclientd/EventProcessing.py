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
Processing of events.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

# pylint: disable=too-many-lines

from contextlib import contextmanager
import codecs
import filecmp
import os
import shutil
import sys
import time
import datetime
import tempfile
import subprocess
from urllib.parse import urlparse
import psutil

from OPSI import System
from OPSI.Object import ProductOnClient
from OPSI.Types import forceInt, forceList, forceUnicode, forceUnicodeLower
from OPSI.Util.Message import (
	ChoiceSubject, MessageSubject, MessageSubjectProxy, NotificationServer,
	ProgressSubjectProxy
)
from OPSI.Util.Thread import KillableThread

from opsicommon.logging import logger, log_context, logging_config, LOG_WARNING

from opsiclientd import __version__
from opsiclientd.Config import Config
from opsiclientd.Events.Utilities.Generators import reconfigureEventGenerators
from opsiclientd.utils import get_include_exclude_product_ids
from opsiclientd.Events.SyncCompleted import SyncCompletedEvent
from opsiclientd.Exceptions import CanceledByUserError, ConfigurationError
from opsiclientd.Localization import _
from opsiclientd.OpsiService import ServiceConnection
from opsiclientd.State import State
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS, RUNNING_ON_DARWIN, RUNNING_ON_LINUX
from opsiclientd.Timeline import Timeline

config = Config()
state = State()
timeline = Timeline()


@contextmanager
def changeDirectory(path):
	'Change the current directory to `path` as long as the context exists.'

	old_dir = os.getcwd()
	os.chdir(path)
	try:
		yield
	finally:
		os.chdir(old_dir)


class EventProcessingThread(KillableThread, ServiceConnection): # pylint: disable=too-many-instance-attributes,too-many-public-methods
	def __init__(self, opsiclientd, event):
		KillableThread.__init__(self)
		ServiceConnection.__init__(self)

		self.opsiclientd = opsiclientd
		self.event = event

		self.running = False
		self.actionCancelled = False
		self.waitCancelled = False

		self.shutdownCancelled = False
		self.shutdownWaitCancelled = False

		self._serviceConnection = None

		self._notificationServer = None

		self._depotShareMounted = False

		self._statusSubject = MessageSubject('status')
		self._messageSubject = MessageSubject('message')
		self._serviceUrlSubject = MessageSubject('configServiceUrl')
		self._clientIdSubject = MessageSubject('clientId')
		self._actionProcessorInfoSubject = MessageSubject('actionProcessorInfo')
		self._opsiclientdInfoSubject = MessageSubject('opsiclientdInfo')
		self._detailSubjectProxy = MessageSubjectProxy('detail')
		self._currentProgressSubjectProxy = ProgressSubjectProxy('currentProgress', fireAlways=False)
		self._overallProgressSubjectProxy = ProgressSubjectProxy('overallProgress', fireAlways=False)
		self._choiceSubject = None

		self._statusSubject.setMessage( _("Processing event %s") % self.event.eventConfig.getName() )
		self._clientIdSubject.setMessage(config.get('global', 'host_id'))
		self._opsiclientdInfoSubject.setMessage(f"opsiclientd {__version__}")
		self._actionProcessorInfoSubject.setMessage("")

		self.isLoginEvent = bool(self.event.eventConfig.actionType == 'login')
		if self.isLoginEvent:
			logger.info("Event is user login event")

	# ServiceConnection
	def connectionThreadOptions(self):
		return {'statusSubject': self._statusSubject}

	def connectionStart(self, configServiceUrl):
		self._serviceUrlSubject.setMessage(configServiceUrl)
		try:
			cancellableAfter = forceInt(config.get('config_service', 'user_cancelable_after'))
			if self._notificationServer and (cancellableAfter >= 0):
				logger.info("User is allowed to cancel connection after %d seconds", cancellableAfter)
				self._choiceSubject = ChoiceSubject(id = 'choice')
		except Exception as err: # pylint: disable=broad-except
			logger.error(err)

	def connectionCancelable(self, stopConnectionCallback):
		if self._notificationServer and self._choiceSubject:
			self._choiceSubject.setChoices([ 'Stop connection' ])
			self._choiceSubject.setCallbacks([ stopConnectionCallback ])
			self._notificationServer.addSubject(self._choiceSubject)

	def connectionTimeoutChanged(self, timeout):
		if self._detailSubjectProxy:
			self._detailSubjectProxy.setMessage( _('Timeout: %ds') % timeout )

	def connectionCanceled(self):
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage('')
		ServiceConnection.connectionCanceled(self)

	def connectionTimedOut(self):
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage('')
		ServiceConnection.connectionTimedOut(self)

	def connectionEstablished(self):
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage('')

	def connectionFailed(self, error):
		if self._notificationServer and self._choiceSubject:
			self._notificationServer.removeSubject(self._choiceSubject)
		self._detailSubjectProxy.setMessage('')
		ServiceConnection.connectionFailed(self, error)

	# End of ServiceConnection

	def getSessionId(self):
		if RUNNING_ON_WINDOWS:
			if self.isLoginEvent:
				user_session_ids = System.getUserSessionIds(self.event.eventInfo["User"])
				if user_session_ids:
					session_id = user_session_ids[0]
					logger.info("Using session id of user '%s': %s", self.event.eventInfo["User"], session_id)
					return session_id

			# Prefer active console/rdp sessions
			for session in System.getActiveSessionInformation():
				if session.get("StateName") == "active":
					session_id = session["SessionId"]
					logger.info("Using session id of user '%s': %s", session.get("UserName"), session_id)
					return session_id

			session_id = System.getActiveConsoleSessionId()
			logger.info("Using active console session id: %s", session_id)
			return session_id

		session_id = System.getActiveSessionId()
		logger.info("Using active session id: %s", session_id)
		return session_id

	def setStatusMessage(self, message):
		logger.debug("Setting status message to: %s", message)
		self._statusSubject.setMessage(message)

	@property
	def notificationServerPort(self):
		if not self._notificationServer:
			return None
		return self._notificationServer.port

	def startNotificationServer(self):
		logger.notice("Starting notification server")

		try:
			self._notificationServer = NotificationServer(
				address=config.get('notification_server', 'interface'),
				start_port=forceInt(config.get('notification_server', 'start_port')),
				subjects=[
					self._statusSubject,
					self._messageSubject,
					self._serviceUrlSubject,
					self._clientIdSubject,
					self._actionProcessorInfoSubject,
					self._opsiclientdInfoSubject,
					self._detailSubjectProxy,
					self._currentProgressSubjectProxy,
					self._overallProgressSubjectProxy
				]
			)
			with log_context({'instance' : 'notification server'}):
				self._notificationServer.daemon = True
				if not self._notificationServer.start_and_wait(timeout=30):
					if self._notificationServer.errorOccurred():
						raise Exception(self._notificationServer.errorOccurred())
					raise Exception("Timed out while waiting for notification server")
				if self._notificationServer.errorOccurred():
					raise Exception(self._notificationServer.errorOccurred())
				logger.notice("Notification server started (listening on port %d)", self.notificationServerPort)
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to start notification server: %s", err)
			raise Exception(f"Failed to start notification server: {err}") from err

	def stopNotificationServer(self):
		if not self._notificationServer:
			return

		try:
			logger.info("Stopping notification server")
			self._notificationServer.stop(stopReactor=False)
		except Exception as err: # pylint: disable=broad-except
			logger.error(err, exc_info=True)

	def getConfigFromService(self):
		''' Get settings from service '''
		logger.notice("Getting config from service")
		try:
			if not self.isConfigServiceConnected():
				logger.warning("Cannot get config from service: not connected")
				return
			self.setStatusMessage(_("Getting config from service"))
			config.getFromService(self._configService)
			self.setStatusMessage(_("Got config from service"))
			logger.notice("Reconfiguring event generators")
			reconfigureEventGenerators()
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to get config from service: %s", err)
			raise

	def writeLogToService(self):
		logger.notice("Writing log to service")
		try:
			if not self.isConfigServiceConnected():
				logger.warning("Cannot write log to service: not connected")
				return
			self.setStatusMessage(_("Writing log to service"))

			with codecs.open(config.get('global', 'log_file'), 'r', 'utf-8', 'replace') as file:
				data = file.read()

			data += "-------------------- submitted part of log file ends here, see the rest of log file on client --------------------\n"
			# Do not log jsonrpc request
			logging_config(file_level=LOG_WARNING)
			self._configService.log_write('clientconnect', data.replace('\ufffd', '?'), config.get('global', 'host_id')) # pylint: disable=no-member
			logging_config(file_level=config.get('global', 'log_level'))
		except Exception as err: # pylint: disable=broad-except
			logging_config(file_level=config.get('global', 'log_level'))
			logger.error("Failed to write log to service: %s", err)
			raise

	def runCommandInSession(self, command, sessionId=None, desktop=None, waitForProcessEnding=False, timeoutSeconds=0, noWindow=False): # pylint: disable=too-many-arguments
		if sessionId is None:
			sessionId = self.getSessionId()

		if not desktop or (forceUnicodeLower(desktop) == 'current'):
			if self.isLoginEvent:
				desktop = 'default'
			else:
				logger.debug("Getting current active desktop name")
				desktop = forceUnicodeLower(self.opsiclientd.getCurrentActiveDesktopName(sessionId))
				logger.debug("Got current active desktop name: %s", desktop)

		if not desktop:
			desktop = 'winlogon'

		processId = None
		while True:
			try:
				logger.info("Running command %s in session '%s' on desktop '%s'", command, sessionId, desktop)
				processId = System.runCommandInSession(
						command=command,
						sessionId=sessionId,
						desktop=desktop,
						waitForProcessEnding=waitForProcessEnding,
						timeoutSeconds=timeoutSeconds,
						noWindow=noWindow
				)[2]
				break
			except Exception as err: # pylint: disable=broad-except
				logger.error(err)
				raise

		return processId

	def startNotifierApplication(self, command, sessionId=None, desktop=None, notifierId=None): # pylint: disable=inconsistent-return-statements
		if sessionId is None:
			sessionId = self.getSessionId()

		logger.notice("Starting notifier application in session '%s' on desktop '%s'", sessionId, desktop)
		try:
			pid = self.runCommandInSession(
				sessionId = sessionId,
				command = command.replace('%port%', forceUnicode(self.notificationServerPort)).replace('%id%', forceUnicode(notifierId)),
				desktop = desktop,
				waitForProcessEnding = False
			)
			return pid
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to start notifier application '%s': %s" , command, err)

	def closeProcessWindows(self, processId):
		try:
			opsiclientd_rpc = config.get('opsiclientd_rpc', 'command')
			command = f'{opsiclientd_rpc} "exit(); System.closeProcessWindows(processId={processId})"'
		except Exception as err: # pylint: disable=broad-except
			raise Exception(f"opsiclientd_rpc command not defined: {err}") from err

		self.runCommandInSession(command=command, waitForProcessEnding=False, noWindow=True)

	def setActionProcessorInfo(self):
		try:
			actionProcessorFilename = config.get('action_processor', 'filename')
			actionProcessorLocalDir = config.get('action_processor', 'local_dir')
			actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)

			if RUNNING_ON_WINDOWS:
				info = System.getFileVersionInfo(actionProcessorLocalFile)

				version = info.get('FileVersion', '')
				name = info.get('FileDescription', '')
				logger.info("Action processor name '%s', version '%s'", name, version)
				self._actionProcessorInfoSubject.setMessage(f"{name} {version}")
			else:
				logger.info("Action processor: %s", actionProcessorLocalFile)
				self._actionProcessorInfoSubject.setMessage(os.path.basename(actionProcessorLocalFile))
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to set action processor info: %s", err)

	def mountDepotShare(self, impersonation):
		if self._depotShareMounted:
			logger.debug("Depot share already mounted")
			return
		if not config.get('depot_server', 'url'):
			raise Exception("Cannot mount depot share, depot_server.url undefined")
		if config.get('depot_server', 'url').split('/')[2] in ('127.0.0.1', 'localhost'):
			logger.notice("No need to mount depot share %s, working on local depot cache", config.get('depot_server', 'url'))
			return

		logger.notice("Mounting depot share %s", config.get('depot_server', 'url'))
		self.setStatusMessage(_("Mounting depot share %s") % config.get('depot_server', 'url'))

		mount_options = {}
		(mount_username, mount_password) = config.getDepotserverCredentials(configService=self._configService)

		if RUNNING_ON_WINDOWS:
			url = urlparse(config.get('depot_server', 'url'))
			try:

				if url.scheme in ("smb", "cifs"):
					System.setRegistryValue(
						System.HKEY_LOCAL_MACHINE,
						f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\ZoneMap\\Domains\\{url.hostname}",
						"file", 1
					)
				elif url.scheme in ("webdavs", "https"):
					System.setRegistryValue(
						System.HKEY_LOCAL_MACHINE,
						f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\ZoneMap\\Domains\\{url.hostname}@SSL@{url.port}",
						"file", 1
					)
					System.setRegistryValue(
						System.HKEY_LOCAL_MACHINE,
						"SYSTEM\\CurrentControlSet\\Services\\WebClient\\Parameters",
						"FileSizeLimitInBytes", 0xffffffff
					)
				logger.info("Added depot '%s' to trusted domains", url.hostname)
			except Exception as err: # pylint: disable=broad-except
				logger.error("Failed to add depot to trusted domains: %s", err)

			if url.scheme in ("smb", "cifs") and impersonation:
				mount_username = None
				mount_password = None
		elif RUNNING_ON_LINUX or RUNNING_ON_DARWIN:
			mount_options["ro"] = ""
			if RUNNING_ON_LINUX:
				mount_options["dir_mode"] = "0700"
				mount_options["file_mode"] = "0700"

		System.mount(
			config.get('depot_server', 'url'), config.getDepotDrive(),
			username=mount_username, password=mount_password,
			**mount_options
		)

		self._depotShareMounted = True

	def umountDepotShare(self):
		if not self._depotShareMounted:
			logger.debug("Depot share not mounted")
			return
		try:
			logger.notice("Unmounting depot share")
			System.umount(config.getDepotDrive())
			self._depotShareMounted = False
		except Exception as err: # pylint: disable=broad-except
			logger.warning(err)

	def updateActionProcessor(self, mount=True): # pylint: disable=too-many-locals,inconsistent-return-statements,too-many-branches,too-many-statements
		logger.notice("Updating action processor")
		self.setStatusMessage(_("Updating action processor"))

		impersonation = None
		try: # pylint: disable=too-many-nested-blocks
			mounted = False
			try:
				url = urlparse(config.get('depot_server', 'url'))
				if mount and url.hostname.lower() not in ('127.0.0.1', 'localhost'):
					impersonation = None
					if RUNNING_ON_WINDOWS:
						# This logon type allows the caller to clone its current token and specify new credentials for outbound connections.
						# The new logon session has the same local identifier but uses different credentials for other network connections.
						(mount_username, mount_password) = config.getDepotserverCredentials(configService=self._configService)
						if url.scheme in ("smb", "cifs"):
							impersonation = System.Impersonate(username=mount_username, password=mount_password)
							impersonation.start(logonType='NEW_CREDENTIALS')

					logger.debug("Not on windows: mounting %s impersonation", "with" if impersonation else "without")
					self.mountDepotShare(impersonation)
					mounted = True

				actionProcessorRemoteDir = None
				actionProcessorCommonDir = None
				if url.hostname.lower() in ('127.0.0.1', 'localhost'):
					dirname = config.get('action_processor', 'remote_dir')
					dirname.lstrip(os.sep)
					dirname.lstrip("install" + os.sep)
					dirname.lstrip(os.sep)
					actionProcessorRemoteDir = os.path.join(
						self.opsiclientd.getCacheService().getProductCacheDir(),
						dirname
					)
					commonname = config.get('action_processor', 'remote_common_dir')
					commonname.lstrip(os.sep)
					commonname.lstrip("install" + os.sep)
					commonname.lstrip(os.sep)
					actionProcessorCommonDir = os.path.join(self.opsiclientd.getCacheService().getProductCacheDir(), commonname)
					logger.notice("Updating action processor from local cache '%s' (common dir '%s')", actionProcessorRemoteDir, actionProcessorCommonDir)
				else:
					#match = re.search('^(smb|cifs)://([^/]+)/([^/]+)(.*)$', config.get('depot_server', 'url'), re.IGNORECASE)
					## 1: protocol, 2: netloc, 3: share_name
					#if not match:
					#	raise Exception("Bad depot-URL '%s'" % config.get('depot_server', 'url'))
					#pn = match.group(3).replace('/', os.sep)
					dd = config.getDepotDrive()
					if RUNNING_ON_WINDOWS:
						dd += os.sep
					dirname = config.get('action_processor', 'remote_dir')
					dirname.lstrip(os.sep)
					#actionProcessorRemoteDir = os.path.join(dd, pn, dirname)
					actionProcessorRemoteDir = os.path.join(dd, dirname)
					commonname = config.get('action_processor', 'remote_common_dir')
					commonname.lstrip(os.sep)
					actionProcessorCommonDir = os.path.join(dd, commonname)
					logger.notice("Updating action processor from depot dir '%s' (common dir '%s')", actionProcessorRemoteDir, actionProcessorCommonDir)

				actionProcessorFilename = config.get('action_processor', 'filename')
				actionProcessorLocalDir = config.get('action_processor', 'local_dir')
				actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)
				actionProcessorRemoteFile = os.path.join(actionProcessorRemoteDir, actionProcessorFilename)

				if not os.path.exists(actionProcessorLocalFile):
					logger.notice("Action processor needs update because file '%s' not found", actionProcessorLocalFile)
				elif abs(os.stat(actionProcessorLocalFile).st_mtime - os.stat(actionProcessorRemoteFile).st_mtime) > 10:
					logger.notice("Action processor needs update because modification time difference is more than 10 seconds")
				elif not filecmp.cmp(actionProcessorLocalFile, actionProcessorRemoteFile):
					logger.notice("Action processor needs update because file changed")
				else:
					logger.notice("Local action processor exists and seems to be up to date")
					if self.event.eventConfig.useCachedProducts:
						self._configService.productOnClient_updateObjects([ # pylint: disable=no-member
							ProductOnClient(
								productId          = config.action_processor_name,
								productType        = 'LocalbootProduct',
								clientId           = config.get('global', 'host_id'),
								installationStatus = 'installed',
								actionProgress     = ''
							)
						])
					return actionProcessorLocalFile

				if not RUNNING_ON_WINDOWS and not RUNNING_ON_LINUX:		# TODO: implement for macos
					logger.error("Update of action processor not implemented on this os")
					return

				if RUNNING_ON_WINDOWS:
					logger.info("Checking if action processor files are in use")
					for proc in psutil.process_iter():
						try:
							full_path = proc.exe()
							if full_path and not os.path.relpath(full_path, actionProcessorLocalDir).startswith(".."):
								raise Exception(f"Action processor files are in use by process '{full_path}''")
						except (PermissionError, psutil.AccessDenied, ValueError):
							pass

				# Update files
				if "opsi-script" in actionProcessorLocalDir:
					self.updateActionProcessorUnified(actionProcessorRemoteDir, actionProcessorCommonDir)
				else:
					self.updateActionProcessorOld(actionProcessorRemoteDir)
				logger.notice("Local action processor successfully updated")

				productVersion = None
				packageVersion = None
				for productOnDepot in self._configService.productOnDepot_getIdents( # pylint: disable=no-member
							productType='LocalbootProduct',
							productId=config.action_processor_name,
							depotId=config.get('depot_server', 'depot_id'),
							returnType='dict'):
					productVersion = productOnDepot['productVersion']
					packageVersion = productOnDepot['packageVersion']
				self._configService.productOnClient_updateObjects([ # pylint: disable=no-member
					ProductOnClient(
						productId=config.action_processor_name,
						productType='LocalbootProduct',
						productVersion=productVersion,
						packageVersion=packageVersion,
						clientId=config.get('global', 'host_id'),
						installationStatus='installed',
						actionProgress='',
						actionResult='successful'
					)
				])

				self.setActionProcessorInfo()
			finally:
				if mounted:
					self.umountDepotShare()

		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to update action processor: %s", err, exc_info=True)
		finally:
			if impersonation:
				try:
					impersonation.end()
				except Exception as err: # pylint: disable=broad-except
					logger.warning(err)

	def updateActionProcessorUnified(self, actionProcessorRemoteDir, actionProcessorCommonDir): # pylint: disable=no-self-use
		actionProcessorFilename = config.get('action_processor', 'filename')
		actionProcessorLocalDir = config.get('action_processor', 'local_dir')
		actionProcessorLocalTmpDir = actionProcessorLocalDir + '.tmp'
		actionProcessorLocalFile = os.path.join(actionProcessorLocalDir, actionProcessorFilename)

		logger.notice("Start copying the action processor files")
		if os.path.exists(actionProcessorLocalTmpDir):
			logger.info("Deleting dir '%s'", actionProcessorLocalTmpDir)
			shutil.rmtree(actionProcessorLocalTmpDir)
		logger.info("Copying from '%s' to '%s'", actionProcessorRemoteDir, actionProcessorLocalTmpDir)
		shutil.copytree(actionProcessorRemoteDir, actionProcessorLocalTmpDir)
		for common in os.listdir(actionProcessorCommonDir):
			source = os.path.join(actionProcessorCommonDir, common)
			if os.path.isdir(source):
				shutil.copytree(source, os.path.join(actionProcessorLocalTmpDir, common))
			else:
				shutil.copy2(source, os.path.join(actionProcessorLocalTmpDir, common))

		if not os.path.exists(os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)):
			raise Exception(f"File '{os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)}' does not exist after copy")

		if os.path.exists(actionProcessorLocalDir):
			logger.info("Deleting dir '%s'", actionProcessorLocalDir)
			shutil.rmtree(actionProcessorLocalDir)

		logger.info("Moving dir '%s' to '%s'", actionProcessorLocalTmpDir, actionProcessorLocalDir)
		shutil.move(actionProcessorLocalTmpDir, actionProcessorLocalDir)

		if RUNNING_ON_WINDOWS:
			logger.notice("Trying to set the right permissions for opsi-script")
			setaclcmd = os.path.join(config.get('global', 'base_dir'), 'utilities', 'setacl.exe')
			opsi_script_dir = actionProcessorLocalDir.replace('\\\\', '\\')
			cmd = (			#TODO: change to icacls
				f'"{setaclcmd}" -on "{opsi_script_dir}" -ot file'
				' -actn ace -ace "n:S-1-5-32-544;p:full;s:y" -ace "n:S-1-5-32-545;p:read_ex;s:y"'
				' -actn clear -clr "dacl,sacl" -actn rstchldrn -rst "dacl,sacl"'
			)
			System.execute(cmd, shell=False)
		elif RUNNING_ON_LINUX:
			symlink = os.path.join("/usr/bin", actionProcessorFilename)
			logger.info("Making symlink '%s' to '%s'", symlink, actionProcessorLocalFile)
			if os.path.exists(symlink):
				if not os.path.islink(symlink):
					logger.warning("replacing binary '%s' with symlink to %s", symlink, actionProcessorLocalFile)
				os.remove(symlink)
			os.symlink(actionProcessorLocalFile, symlink)

	def updateActionProcessorOld(self, actionProcessorRemoteDir): # pylint: disable=no-self-use
		actionProcessorFilename = config.get('action_processor', 'filename')
		actionProcessorLocalDir = config.get('action_processor', 'local_dir')
		actionProcessorLocalTmpDir = actionProcessorLocalDir + '.tmp'

		logger.notice("Start copying the action processor files")
		if RUNNING_ON_WINDOWS:
			if os.path.exists(actionProcessorLocalTmpDir):
				logger.info("Deleting dir '%s'", actionProcessorLocalTmpDir)
				shutil.rmtree(actionProcessorLocalTmpDir)
			logger.info("Copying from '%s' to '%s'", actionProcessorRemoteDir, actionProcessorLocalTmpDir)
			shutil.copytree(actionProcessorRemoteDir, actionProcessorLocalTmpDir)

			if not os.path.exists(os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)):
				raise Exception(f"File '{os.path.join(actionProcessorLocalTmpDir, actionProcessorFilename)}' does not exist after copy")

			if os.path.exists(actionProcessorLocalDir):
				logger.info("Deleting dir '%s'", actionProcessorLocalDir)
				shutil.rmtree(actionProcessorLocalDir)

			logger.info("Moving dir '%s' to '%s'", actionProcessorLocalTmpDir, actionProcessorLocalDir)
			shutil.move(actionProcessorLocalTmpDir, actionProcessorLocalDir)

			logger.notice("Trying to set the right permissions for opsi-winst")
			setaclcmd = os.path.join(config.get('global', 'base_dir'), 'utilities', 'setacl.exe')
			winstdir = actionProcessorLocalDir.replace('\\\\', '\\')
			cmd = (
				f'"{setaclcmd}" -on "{winstdir}" -ot file'
				' -actn ace -ace "n:S-1-5-32-544;p:full;s:y" -ace "n:S-1-5-32-545;p:read_ex;s:y"'
				' -actn clear -clr "dacl,sacl" -actn rstchldrn -rst "dacl,sacl"'
			)
			System.execute(cmd, shell=False)
		elif RUNNING_ON_LINUX:
			logger.info("Copying from '%s' to '%s'", actionProcessorRemoteDir, actionProcessorLocalDir)
			for fn in os.listdir(actionProcessorRemoteDir):
				if os.path.isfile(os.path.join(actionProcessorRemoteDir, fn)):
					shutil.copy2(
						os.path.join(actionProcessorRemoteDir, fn),
						os.path.join(actionProcessorLocalDir, fn)
					)
				else:
					logger.warning("Skipping '%s' while updating action processor because it is not a file",
						os.path.join(actionProcessorRemoteDir, fn)
					)

	def processUserLoginActions(self):
		self.setStatusMessage(_("Processing login actions"))
		try:
			if not self._configService:
				raise Exception("Not connected to config service")

			productsByIdAndVersion = {}
			for product in self._configService.product_getObjects(type='LocalbootProduct', userLoginScript="*.*"): # pylint: disable=no-member
				if product.id not in productsByIdAndVersion:
					productsByIdAndVersion[product.id] = {}
				if product.productVersion not in productsByIdAndVersion[product.id]:
					productsByIdAndVersion[product.id][product.productVersion] = {}
				productsByIdAndVersion[product.id][product.productVersion][product.packageVersion] = product

			if not productsByIdAndVersion:
				logger.notice("No user login script found, nothing to do")
				return

			clientToDepotservers = self._configService.configState_getClientToDepotserver(clientIds = config.get('global', 'host_id')) # pylint: disable=no-member
			if not clientToDepotservers:
				raise Exception(f"Failed to get depotserver for client '{config.get('global', 'host_id')}'")
			depotId = clientToDepotservers[0]['depotId']

			dd = config.getDepotDrive()
			if RUNNING_ON_WINDOWS:
				dd += os.sep
			productDir = os.path.join(dd, "install")

			userLoginScripts = []
			productIds = []
			for productOnDepot in self._configService.productOnDepot_getIdents( # pylint: disable=no-member
							productType = 'LocalbootProduct',
							depotId     = depotId,
							returnType  = 'dict'):
				product = productsByIdAndVersion.get(
					productOnDepot['productId'], {}).get(
						productOnDepot['productVersion'], {}).get(
							productOnDepot['packageVersion'])
				if not product:
					continue
				logger.info("User login script '%s' found for product %s_%s-%s",
					product.userLoginScript, product.id, product.productVersion, product.packageVersion
				)
				userLoginScripts.append(os.path.join(productDir, product.userLoginScript))
				productIds.append(product.id)

			if not userLoginScripts:
				logger.notice("No user login script found, nothing to do")
				return

			logger.notice("User login scripts found, executing")
			additionalParams = f"/usercontext {self.event.eventInfo.get('User')}"
			self.runActions(productIds, additionalParams)

		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to process login actions: %s", err, exc_info=True)
			self.setStatusMessage(_("Failed to process login actions: %s") % forceUnicode(err))

	def processProductActionRequests(self): # pylint: disable=too-many-branches,too-many-statements
		self.setStatusMessage(_("Getting action requests from config service"))

		try:
			bootmode = ""
			if RUNNING_ON_WINDOWS:
				try:
					bootmode = System.getRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\general", "bootmode").upper()
				except Exception as err: # pylint: disable=broad-except
					logger.warning("Failed to get bootmode from registry: %s", err)
			else:
				bootmode = "BKSTD"

			if not self._configService:
				raise Exception("Not connected to config service")

			productIds = []
			includeProductIds = []
			excludeProductIds = []
			if self.event.eventConfig.actionProcessorProductIds:
				productIds = self.event.eventConfig.actionProcessorProductIds

			if not productIds:
				includeProductGroupIds = [x for x in forceList(self.event.eventConfig.includeProductGroupIds) if x != ""]
				excludeProductGroupIds = [x for x in forceList(self.event.eventConfig.excludeProductGroupIds) if x != ""]
				includeProductIds, excludeProductIds = get_include_exclude_product_ids(
					self._configService, includeProductGroupIds, excludeProductGroupIds
				)

				for productOnClient in [poc for poc in self._configService.productOnClient_getObjects( # pylint: disable=no-member
							productType='LocalbootProduct',
							clientId=config.get('global', 'host_id'),
							actionRequest=['setup', 'uninstall', 'update', 'always', 'once', 'custom'],
							attributes=['actionRequest'],
							productId=includeProductIds) if poc.productId not in excludeProductIds]:
					if productOnClient.productId not in productIds:
						productIds.append(productOnClient.productId)
						logger.notice(
							"   [%2s] product %-20s %s",
							len(productIds), productOnClient.productId + ':', productOnClient.actionRequest
						)

			if (not productIds) and bootmode == 'BKSTD':
				logger.notice("No product action requests set")
				self.setStatusMessage( _("No product action requests set") )
				#set installation_pending State to False
				state.set('installation_pending','false')
				try:
					if self.event.eventConfig.useCachedConfig:
						self.opsiclientd.getCacheService().setConfigCacheObsolete()
				except Exception as err: # pylint: disable=broad-except
					logger.error(err)
			else:
				#set installation_pending State
				if not self.event.eventConfig.actionProcessorProductIds:
					state.set('installation_pending','true')

				logger.notice("Start processing action requests")
				if productIds:
					if self.event.eventConfig.useCachedProducts:
						if self.opsiclientd.getCacheService().productCacheCompleted(self._configService, productIds):
							logger.notice("Event '%s' uses cached products and product caching is done", self.event.eventConfig.getId())
						else:
							raise Exception(
								f"Event '{self.event.eventConfig.getId()}' uses cached products but product caching is not done"
							)

				additionalParams = ""
				if includeProductIds or excludeProductIds:
					additionalParams = "/processproducts " + ','.join(productIds)

				self.processActionWarningTime(productIds)
				self.runActions(productIds, additionalParams=additionalParams)
				try:
					if self.event.eventConfig.useCachedConfig and not self._configService.productOnClient_getIdents( # pylint: disable=no-member
								productType   = 'LocalbootProduct',
								clientId      = config.get('global', 'host_id'),
								actionRequest = ['setup', 'uninstall', 'update', 'always', 'once', 'custom']):
						self.opsiclientd.getCacheService().setConfigCacheObsolete()
					if not self._configService.productOnClient_getIdents( # pylint: disable=no-member
								productType   = 'LocalbootProduct',
								clientId      = config.get('global', 'host_id'),
								actionRequest = ['setup', 'uninstall', 'update', 'once', 'custom']):
						#set installation_pending State to false nothing to do!!!!
						logger.notice("Setting installation pending to false")
						state.set('installation_pending','false')
				except Exception as err: # pylint: disable=broad-except
					logger.error(err)

		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to process product action requests: %s", err, exc_info=True)
			self.setStatusMessage(_("Failed to process product action requests: %s") % str(err))
			timeline.addEvent(
				title="Failed to process product action requests",
				description=f"Failed to process product action requests: {err}",
				category="error",
				isError=True
			)
		time.sleep(3)

	def runActions(self, productIds, additionalParams=''): # pylint: disable=too-many-nested-blocks,too-many-locals,too-many-branches,too-many-statements
		runActionsEventId = timeline.addEvent(
			title="Running actions",
			description=f"Running actions {', '.join(productIds)}",
			category="run_actions",
			durationEvent=True
		)
		try:
			config.selectDepotserver(
				configService=self._configService,
				mode="mount",
				event=self.event,
				productIds=productIds
			)
			if not additionalParams:
				additionalParams = ''
			if not self.event.getActionProcessorCommand():
				raise Exception("No action processor command defined")

			if (
				RUNNING_ON_WINDOWS and
				sys.getwindowsversion().major >= 6 and # pylint: disable=no-member
				self.event.eventConfig.name == 'gui_startup' and
				self.event.eventConfig.trustedInstallerDetection
			):
				# Wait for windows installer before Running Action Processor
				try:
					logger.notice("Getting windows installer status")
					if self.opsiclientd.isWindowsInstallerBusy():
						logger.notice("Windows installer is running, waiting until upgrade process is finished")
						self.setStatusMessage(_("Waiting for TrustedInstaller"))
						waitEventId = timeline.addEvent(
							title = "Waiting for TrustedInstaller",
							description = "Windows installer is running, waiting until upgrade process is finished",
							category = "wait",
							durationEvent = True
						)

						while self.opsiclientd.isWindowsInstallerBusy():
							time.sleep(10)
							logger.debug("Windows installer is running, waiting until upgrade process is finished")

						logger.notice("Windows installer finished")
						timeline.setEventEnd(eventId=waitEventId)
					else:
						logger.notice("Windows installer not running")
				except Exception as err: # pylint: disable=broad-except
					logger.error("Failed to get windows installer status: %s", err)

			self.setStatusMessage(_("Starting actions"))

			if RUNNING_ON_WINDOWS:
				# Setting some registry values before starting action
				# Mainly for action processor
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depoturl",   config.get('depot_server', 'url'))
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "depotdrive", config.getDepotDrive())
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "configurl",   "<deprecated>")
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "configdrive", "<deprecated>")
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "utilsurl",    "<deprecated>")
				System.setRegistryValue(System.HKEY_LOCAL_MACHINE, "SOFTWARE\\opsi.org\\shareinfo", "utilsdrive",  "<deprecated>")

			# action processor desktop can be one of current / winlogon / default
			desktop = self.event.eventConfig.actionProcessorDesktop

			# Choose desktop for action processor
			if not desktop or (forceUnicodeLower(desktop) == 'current'):
				if self.isLoginEvent:
					desktop = 'default'
				else:
					desktop = forceUnicodeLower(self.opsiclientd.getCurrentActiveDesktopName(self.getSessionId()))
					if desktop and desktop.lower() == 'screen-saver':
						desktop = 'default'

			if not desktop:
				# Default desktop is winlogon
				desktop = 'winlogon'

			depotServerUsername = ''
			depotServerPassword = ''
			try:
				(depotServerUsername, depotServerPassword) = config.getDepotserverCredentials(configService=self._configService)
			except Exception as err: # pylint: disable=broad-except
				if not self.event.eventConfig.useCachedProducts:
					raise
				logger.error("Failed to get depotserver credentials, continuing because event uses cached products", exc_info=True)
				depotServerUsername = 'pcpatch'

			if not RUNNING_ON_WINDOWS:
				self.mountDepotShare(None)

			# Update action processor
			if self.event.eventConfig.updateActionProcessor:
				if RUNNING_ON_DARWIN:
					logger.warning("Update of action processor currently not implemented for MacOS")
				else:
					self.updateActionProcessor(mount=not self._depotShareMounted)

			# Run action processor
			serviceSession = 'none'
			try:
				serviceSession = self.getConfigService().jsonrpc_getSessionId()
				if not serviceSession:
					serviceSession = 'none'
			except Exception: # pylint: disable=broad-except
				pass

			actionProcessorUserName = ''
			actionProcessorUserPassword = ''
			if not self.isLoginEvent:
				actionProcessorUserName = self.opsiclientd._actionProcessorUserName # pylint: disable=protected-access
				actionProcessorUserPassword = self.opsiclientd._actionProcessorUserPassword # pylint: disable=protected-access

			createEnvironment = config.get('action_processor', 'create_environment')

			actionProcessorCommand = config.replace(self.event.getActionProcessorCommand())
			actionProcessorCommand = actionProcessorCommand.replace('%service_url%', self._configServiceUrl)
			actionProcessorCommand = actionProcessorCommand.replace('%service_session%', serviceSession)
			actionProcessorCommand = actionProcessorCommand.replace(
				'%action_processor_productids%',
				",".join(self.event.eventConfig.actionProcessorProductIds)
			)
			actionProcessorCommand += f" {additionalParams}"
			actionProcessorCommand = actionProcessorCommand.replace('"', '\\"')

			if RUNNING_ON_WINDOWS:
				command = (
					f'"{os.path.join(os.path.dirname(sys.argv[0]), "action_processor_starter.exe")}"' +
					r' "%global.host_id%" "%global.opsi_host_key%" "%control_server.port%"'
					r' "%global.log_file%" "%global.log_level%" "%depot_server.url%"'
					f' "{config.getDepotDrive()}" "{depotServerUsername}" "{depotServerPassword}"'
					f' "{self.getSessionId()}" "{desktop}" '
					f' "{actionProcessorCommand}" "{self.event.eventConfig.actionProcessorTimeout}"'
					f' "{actionProcessorUserName}" "{actionProcessorUserPassword}"'
					f' "{str(createEnvironment).lower()}"'
				)
			else:
				command = actionProcessorCommand

			command = config.replace(command)

			if self.event.eventConfig.preActionProcessorCommand:
				logger.notice(
					"Starting pre action processor command '%s' in session '%s' on desktop '%s'",
					self.event.eventConfig.preActionProcessorCommand, self.getSessionId(), desktop
				)
				self.runCommandInSession(
					command = self.event.eventConfig.preActionProcessorCommand,
					desktop = desktop,
					waitForProcessEnding = True
				)

			if RUNNING_ON_WINDOWS:
				logger.notice(
					"Starting action processor in session '%s' on desktop '%s'",
					self.getSessionId(), desktop
				)
				self.runCommandInSession(
					command=command,
					desktop=desktop,
					waitForProcessEnding=True,
					noWindow=True
				)
			else:
				with changeDirectory('/tmp'):
					credentialfile = None
					try:
						(username, password) = (None, None)
						new_cmd = []
						cmd = command.split()
						skip_next = False
						for num, part in enumerate(cmd):
							if skip_next:
								skip_next = False
								continue
							if part.strip().lower() == "-username" and len(cmd) > num:
								username = cmd[num+1].strip()
								skip_next = True
							elif part.strip().lower() == "-password" and len(cmd) > num:
								password = cmd[num+1].strip()
								skip_next = True
							else:
								new_cmd.append(part)
						if username is not None and password is not None:
							tf = tempfile.NamedTemporaryFile(mode="w", delete=False, encoding="utf-8")
							tf.write(f"username={username}\npassword={password}\n")
							tf.close()
							credentialfile = tf.name
							new_cmd.extend(["-credentialfile", credentialfile])
							command = " ".join(new_cmd)

						if cmd and cmd[0] and os.path.isfile(cmd[0]) and not os.access(cmd[0], os.X_OK):
							os.chmod(cmd[0], 0o0755)

						self.setStatusMessage(_("Action processor is running"))
						System.runCommandInSession(
							command=command,
							sessionId=self.getSessionId(),
							waitForProcessEnding=True,
							timeoutSeconds=self.event.eventConfig.actionProcessorTimeout
						)
					finally:
						if credentialfile and os.path.exists(credentialfile):
							os.unlink(credentialfile)

			if self.event.eventConfig.postActionProcessorCommand:
				logger.notice("Starting post action processor command '%s' in session '%s' on desktop '%s'",
					self.event.eventConfig.postActionProcessorCommand, self.getSessionId(), desktop
				)
				self.runCommandInSession(
					command = self.event.eventConfig.postActionProcessorCommand,
					desktop = desktop,
					waitForProcessEnding = True
				)

			self.setStatusMessage( _("Actions completed") )
		finally:
			timeline.setEventEnd(eventId = runActionsEventId)
			self.umountDepotShare()

	def setEnvironment(self): # pylint: disable=no-self-use
		try:
			logger.debug("Current environment:")
			for (key, value) in os.environ.items():
				logger.debug("   %s=%s", key, value)
			logger.debug("Updating environment")
			hostname = os.environ['COMPUTERNAME']
			(homeDrive, homeDir) = os.environ['USERPROFILE'].split('\\')[0:2]
			# TODO: is this correct?
			username = config.get('global', 'username')
			# TODO: Anwendungsdaten
			os.environ['APPDATA']     = f"{homeDrive}\\{homeDir}\\{username}\\AppData\\Roaming"
			os.environ['HOMEDRIVE']   = homeDrive
			os.environ['HOMEPATH']    = f"\\{homeDir}\\{username}"
			os.environ['LOGONSERVER'] = f"\\\\{hostname}"
			os.environ['SESSIONNAME'] = 'Console'
			os.environ['USERDOMAIN']  = hostname
			os.environ['USERNAME']    = username
			os.environ['USERPROFILE'] = f"{homeDrive}\\{homeDir}\\{username}"
			logger.debug("Updated environment:")
			for (key, value) in os.environ.items():
				logger.debug("   %s=%s", key, value)
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to set environment: %s", err)

	def abortActionCallback(self, choiceSubject): # pylint: disable=unused-argument
		logger.notice("Event aborted by user")
		self.actionCancelled = True

	def startActionCallback(self, choiceSubject): # pylint: disable=unused-argument
		logger.notice("Event wait cancelled by user")
		self.waitCancelled = True

	def processActionWarningTime(self, productIds=[]): # pylint: disable=dangerous-default-value,too-many-branches,too-many-statements,too-many-locals
		if not self.event.eventConfig.actionWarningTime:
			return
		logger.info("Notifying user of actions to process %s (%s)", self.event, productIds)
		cancelCounter = state.get(f'action_processing_cancel_counter_{self.event.eventConfig.name}', 0)
		# State action_processing_cancel_counter without appended event name is needed for notification server
		state.set('action_processing_cancel_counter', cancelCounter)

		waitEventId = timeline.addEvent(
			title="Action warning",
			description=(
				f"Notifying user of actions to process {self.event.eventConfig.getId()} ({', '.join(productIds)})\n"
				f"actionWarningTime: {self.event.eventConfig.actionWarningTime}, "
				f"actionUserCancelable: {self.event.eventConfig.actionUserCancelable}, "
				f"cancelCounter: {cancelCounter}"
			),
			category="wait",
			durationEvent=True
		)
		self._messageSubject.setMessage("%s\n%s: %s" % (
			self.event.eventConfig.getActionMessage(),
			_("Products"),
			', '.join(productIds))
		)
		choiceSubject = ChoiceSubject(id='choice')
		if cancelCounter < self.event.eventConfig.actionUserCancelable:
			choiceSubject.setChoices([ _('Abort'), _('Start now') ])
			choiceSubject.setCallbacks( [ self.abortActionCallback, self.startActionCallback ] )
		else:
			choiceSubject.setChoices([ _('Start now') ])
			choiceSubject.setCallbacks( [ self.startActionCallback ] )
		self._notificationServer.addSubject(choiceSubject)
		notifierPids = []
		try:
			if self.event.eventConfig.actionNotifierCommand:
				desktops = [self.event.eventConfig.actionNotifierDesktop]
				if RUNNING_ON_WINDOWS and self.event.eventConfig.actionNotifierDesktop == "all":
					desktops = ["winlogon", "default"]
				for desktop in desktops:
					notifier_pid = self.startNotifierApplication(
						command    = self.event.eventConfig.actionNotifierCommand,
						desktop    = desktop,
						notifierId = 'action'
					)
					if notifier_pid:
						notifierPids.append(notifier_pid)

			timeout = int(self.event.eventConfig.actionWarningTime)
			endTime = time.time() + timeout
			while timeout > 0 and not self.actionCancelled and not self.waitCancelled:
				now = time.time()
				minutes = 0
				seconds = endTime - now
				if seconds >= 60:
					minutes = int(seconds/60)
					seconds -= minutes*60
				seconds = int(seconds)
				if minutes < 10:
					minutes = f"0{minutes}"
				if seconds < 10:
					seconds = f"0{seconds}"
				self.setStatusMessage(_("Event %s: action processing will start in %s:%s") % (self.event.eventConfig.getName(), minutes, seconds))
				if endTime - now <= 0:
					break
				time.sleep(1)

			if self.waitCancelled:
				timeline.addEvent(
					title="Action processing started by user",
					description="Action processing wait time cancelled by user",
					category="user_interaction"
				)

			if self.actionCancelled:
				cancelCounter += 1
				state.set(f"action_processing_cancel_counter_{self.event.eventConfig.name}", cancelCounter)
				logger.notice("Action processing cancelled by user for the %d. time (max: %d)",
					cancelCounter, self.event.eventConfig.actionUserCancelable
				)
				timeline.addEvent(
					title="Action processing cancelled by user",
					description=(
						f"Action processing cancelled by user for the {cancelCounter}. time"
						f" (max: {self.event.eventConfig.actionUserCancelable})"
					),
					category="user_interaction")
				raise CanceledByUserError("Action processing cancelled by user")
			state.set(f'action_processing_cancel_counter_{self.event.eventConfig.name}', 0)
		finally:
			timeline.setEventEnd(waitEventId)
			try:
				if self._notificationServer:
					self._notificationServer.requestEndConnections(['action'])
					self._notificationServer.removeSubject(choiceSubject)
				if notifierPids:
					try:
						time.sleep(3)
						for notifierPid in notifierPids:
							System.terminateProcess(processId=notifierPid)
					except Exception: # pylint: disable=broad-except
						pass

			except Exception as err: # pylint: disable=broad-except
				logger.error(err, exc_info=True)

	def abortShutdownCallback(self, choiceSubject): # pylint: disable=unused-argument
		logger.notice("Shutdown aborted by user")
		self.shutdownCancelled = True

	def startShutdownCallback(self, choiceSubject): # pylint: disable=unused-argument
		logger.notice("Shutdown wait cancelled by user")
		self.shutdownWaitCancelled = True

	def isRebootRequested(self):
		if self.event.eventConfig.reboot:
			return True
		if self.event.eventConfig.processShutdownRequests and self.opsiclientd.isRebootRequested():
			return True
		return False

	def isShutdownRequested(self):
		if self.event.eventConfig.shutdown:
			return True
		if self.event.eventConfig.processShutdownRequests and self.opsiclientd.isShutdownRequested():
			return True
		return False

	def processShutdownRequests(self): # pylint: disable=too-many-locals,too-many-branches,too-many-statements
		try: # pylint: disable=too-many-nested-blocks
			shutdown = self.isShutdownRequested()
			reboot   = self.isRebootRequested()
			if reboot or shutdown:
				if reboot:
					timeline.addEvent(title = "Reboot requested", category = "system")
					self.setStatusMessage(_("Reboot requested"))
				else:
					timeline.addEvent(title = "Shutdown requested", category = "system")
					self.setStatusMessage(_("Shutdown requested"))

				if self.event.eventConfig.shutdownWarningTime:
					if not self.event.eventConfig.shutdownNotifierCommand:
						raise ConfigurationError(
							f"Event {self.event.eventConfig.getName()} defines shutdownWarningTime"
							" but shutdownNotifierCommand is not set"
						)
					if self._notificationServer:
						self._notificationServer.requestEndConnections()
					while True:
						shutdownCancelCounter = state.get('shutdown_cancel_counter', 0)
						waitEventId = None
						if reboot:
							logger.info("Notifying user of reboot")
							waitEventId = timeline.addEvent(
								title="Reboot warning",
								description=(
									"Notifying user of reboot\n"
									f"shutdownWarningTime: {self.event.eventConfig.shutdownWarningTime}, "
									f"shutdownUserCancelable: {self.event.eventConfig.shutdownUserCancelable}, "
									f"shutdownCancelCounter: {shutdownCancelCounter}"
								),
								category="wait",
								durationEvent=True
							)
						else:
							logger.info("Notifying user of shutdown")
							waitEventId = timeline.addEvent(
								title="Shutdown warning",
								description=(
									"Notifying user of shutdown\n"
									f"shutdownWarningTime: {self.event.eventConfig.shutdownWarningTime}, "
									f"shutdownUserCancelable: {self.event.eventConfig.shutdownUserCancelable}, "
									f"shutdownCancelCounter: {shutdownCancelCounter}"
								),
								category="wait",
								durationEvent=True
							)

						self.shutdownCancelled = False
						self.shutdownWaitCancelled = False

						shutdownWarningMessage = self.event.eventConfig.getShutdownWarningMessage()
						if isinstance(self.event, SyncCompletedEvent):
							try:
								productIds = list(self.opsiclientd.getCacheService().getProductCacheState()["products"])
								if productIds:
									shutdownWarningMessage += f"\n{_('Products')}: {', '.join(productIds)}"
							except Exception as stateErr: # pylint: disable=broad-except
								logger.error(stateErr, exc_info=True)
						self._messageSubject.setMessage(shutdownWarningMessage)

						choiceSubject = ChoiceSubject(id = 'choice')
						if shutdownCancelCounter < self.event.eventConfig.shutdownUserCancelable:
							if reboot:
								choiceSubject.setChoices([ _('Reboot now'), _('Later') ])
							else:
								choiceSubject.setChoices([ _('Shutdown now'), _('Later') ])
							choiceSubject.setCallbacks( [ self.startShutdownCallback, self.abortShutdownCallback ] )
						else:
							if reboot:
								choiceSubject.setChoices([ _('Reboot now') ])
							else:
								choiceSubject.setChoices([ _('Shutdown now') ])
							choiceSubject.setCallbacks( [ self.startShutdownCallback ] )
						self._notificationServer.addSubject(choiceSubject)

						failed_to_start_notifier = False
						notifierPids = []
						desktops = [self.event.eventConfig.shutdownNotifierDesktop]
						if RUNNING_ON_WINDOWS and self.event.eventConfig.shutdownNotifierDesktop == "all":
							desktops = ["winlogon", "default"]
						for desktop in desktops:
							notifier_pid = self.startNotifierApplication(
								command    = self.event.eventConfig.shutdownNotifierCommand,
								desktop    = desktop,
								notifierId = 'shutdown'
							)
							if notifier_pid:
								notifierPids.append(notifier_pid)
							else:
								logger.error("Failed to start shutdown notifier, shutdown will not be executed")
								failed_to_start_notifier = True

						timeout = int(self.event.eventConfig.shutdownWarningTime)
						endTime = time.time() + timeout
						while (timeout > 0) and not self.shutdownCancelled and not self.shutdownWaitCancelled:
							now = time.time()
							minutes = 0
							seconds = (endTime - now)
							if seconds >= 60:
								minutes = int(seconds/60)
								seconds -= minutes*60
							seconds = int(seconds)
							if minutes < 10:
								minutes = f"0{minutes}"
							if seconds < 10:
								seconds = f"0{seconds}"
							if reboot:
								self.setStatusMessage(_("Reboot in %s:%s") % (minutes, seconds))
							else:
								self.setStatusMessage(_("Shutdown in %s:%s") % (minutes, seconds))
							if (endTime - now) <= 0:
								break
							time.sleep(1)

						try:
							if self._notificationServer:
								self._notificationServer.requestEndConnections()
								self._notificationServer.removeSubject(choiceSubject)
							if notifierPids:
								try:
									time.sleep(3)
									for notifierPid in notifierPids:
										System.terminateProcess(processId=notifierPid)
								except Exception: # pylint: disable=broad-except
									pass
						except Exception as err: # pylint: disable=broad-except
							logger.error(err, exc_info=True)

						self._messageSubject.setMessage("")

						timeline.setEventEnd(waitEventId)

						if self.shutdownWaitCancelled:
							if reboot:
								timeline.addEvent(
									title="Reboot started by user",
									description="Reboot wait time cancelled by user",
									category="user_interaction"
								)
							else:
								timeline.addEvent(
									title="Shutdown started by user",
									description="Shutdown wait time cancelled by user",
									category="user_interaction"
								)

						if self.shutdownCancelled or failed_to_start_notifier:
							self.opsiclientd.setBlockLogin(False)
							shutdown_type = "Reboot" if reboot else "Shutdown"

							if failed_to_start_notifier:
								logger.warning("%s cancelled because user could not be notified.", shutdown_type)
							else:
								shutdownCancelCounter += 1
								state.set('shutdown_cancel_counter', shutdownCancelCounter)
								logger.notice("Shutdown cancelled by user for the %d. time (max: %d)",
									shutdownCancelCounter, self.event.eventConfig.shutdownUserCancelable
								)
								timeline.addEvent(
									title=f"{shutdown_type} cancelled by user",
									description=(
										f"{shutdown_type} cancelled by user for the {shutdownCancelCounter}. time"
										f" (max: {self.event.eventConfig.shutdownUserCancelable})"
									),
									category="user_interaction"
								)

							if self.event.eventConfig.shutdownWarningRepetitionTime >= 0:
								logger.info("Shutdown warning will be repeated in %d seconds",
									self.event.eventConfig.shutdownWarningRepetitionTime
								)
								for _second in range(self.event.eventConfig.shutdownWarningRepetitionTime):
									time.sleep(1)
								continue
						break
				if reboot:
					timeline.addEvent(title="Rebooting", category="system")
					self.opsiclientd.rebootMachine()
				elif shutdown:
					timeline.addEvent(title="Shutting down", category="system")
					self.opsiclientd.shutdownMachine()
		except Exception as err: # pylint: disable=broad-except
			logger.error(err, exc_info=True)

	def inWorkingWindow(self):
		start_str, end_str, now = (None, None, None)
		try:
			# Working window is specified like: 07:00-22:00
			start_str, end_str = self.event.eventConfig.workingWindow.split("-")
			start = datetime.time(int(start_str.split(":")[0]), int(start_str.split(":")[1]))
			end = datetime.time(int(end_str.split(":")[0]), int(end_str.split(":")[1]))
			now = datetime.datetime.now().time()

			logger.debug("Working window configuration: start=%s, end=%s, now=%s", start, end, now)

			in_window = False
			if start <= end:
				in_window = start <= now <= end
			else:
				# Crosses midnight
				in_window = now >= start or now <= end

			if in_window:
				logger.info("Current time %s is within the configured working window (%s-%s)", now, start, end)
				return True

			logger.info("Current time %s is outside the configured working window (%s-%s)", now, start, end)
			return False

		except Exception as err: # pylint: disable=broad-except
			logger.error(
				"Working window processing failed (start=%s, end=%s, now=%s): %s",
				start_str, end_str, now, err, exc_info=True
			)
			return True

	def run(self): # pylint: disable=too-many-branches,too-many-statements
		with log_context({'instance' : f'event processing {self.event.eventConfig.getId()}'}):
			timelineEventId = None
			try: # pylint: disable=too-many-nested-blocks
				if self.event.eventConfig.workingWindow:
					if not self.inWorkingWindow():
						logger.notice("We are not in the configured working window, stopping Event")
						return
				logger.notice(
					"============= EventProcessingThread for occurrcence of event '%s' started =============",
					self.event.eventConfig.getId()
				)
				timelineEventId = timeline.addEvent(
					title=f"Processing event {self.event.eventConfig.getName()}",
					description=f"EventProcessingThread for occurrcence of event '{self.event.eventConfig.getId()}' started",
					category="event_processing",
					durationEvent=True
				)
				self.running = True
				self.actionCancelled = False
				self.waitCancelled = False
				if not self.event.eventConfig.blockLogin:
					self.opsiclientd.setBlockLogin(False)

				notifierPids = []
				try:
					config.setTemporaryDepotDrive(None)
					config.setTemporaryConfigServiceUrls([])

					self.startNotificationServer()
					self.setActionProcessorInfo()
					self._messageSubject.setMessage(self.event.eventConfig.getActionMessage())

					self.setStatusMessage(_("Processing event %s") % self.event.eventConfig.getName())

					if self.event.eventConfig.blockLogin:
						self.opsiclientd.setBlockLogin(True)
					else:
						self.opsiclientd.setBlockLogin(False)
					if self.event.eventConfig.logoffCurrentUser:
						System.logoffCurrentUser()
						time.sleep(15)
					elif self.event.eventConfig.lockWorkstation:
						System.lockWorkstation()
						time.sleep(15)

					if self.event.eventConfig.eventNotifierCommand:
						desktops = [self.event.eventConfig.eventNotifierDesktop]
						if RUNNING_ON_WINDOWS and self.event.eventConfig.eventNotifierDesktop == "all":
							desktops = ["winlogon", "default"]
						for desktop in desktops:
							notifier_pid = self.startNotifierApplication(
								command    = self.event.eventConfig.eventNotifierCommand,
								desktop    = desktop,
								notifierId = 'event'
							)
							if notifier_pid:
								notifierPids.append(notifier_pid)

					if self.event.eventConfig.syncConfigToServer or self.event.eventConfig.syncConfigFromServer:
						if self.opsiclientd.getCacheService().isConfigCacheServiceWorking():
							logger.info("Already syncing config")
						else:
							if self.event.eventConfig.syncConfigToServer:
								self.setStatusMessage( _("Syncing config to server") )
								self.opsiclientd.getCacheService().syncConfigToServer(waitForEnding = True)
								self.setStatusMessage( _("Sync completed") )

							if self.event.eventConfig.syncConfigFromServer:
								self.setStatusMessage( _("Syncing config from server") )
								waitForEnding = self.event.eventConfig.useCachedConfig
								self.opsiclientd.getCacheService().syncConfigFromServer(waitForEnding = waitForEnding)
								if waitForEnding:
									self.setStatusMessage( _("Sync completed") )

					if self.event.eventConfig.cacheProducts:
						if self.opsiclientd.getCacheService().isProductCacheServiceWorking():
							logger.info("Already caching products")
						else:
							self.setStatusMessage( _("Caching products") )
							try:
								self._currentProgressSubjectProxy.attachObserver(self._detailSubjectProxy)
								waitForEnding = self.event.eventConfig.useCachedProducts
								self.opsiclientd.getCacheService().cacheProducts(
									waitForEnding           = waitForEnding,
									productProgressObserver = self._currentProgressSubjectProxy,
									overallProgressObserver = self._overallProgressSubjectProxy,
									dynamicBandwidth        = self.event.eventConfig.cacheDynamicBandwidth,
									maxBandwidth            = self.event.eventConfig.cacheMaxBandwidth
								)
								if waitForEnding:
									self.setStatusMessage(_("Products cached"))
							finally:
								self._detailSubjectProxy.setMessage("")
								try:
									self._currentProgressSubjectProxy.detachObserver(self._detailSubjectProxy)
									self._currentProgressSubjectProxy.reset()
									self._overallProgressSubjectProxy.reset()
								except Exception as err: # pylint: disable=broad-except
									logger.error(err, exc_info=True)

					if self.event.eventConfig.useCachedConfig:
						if self.opsiclientd.getCacheService().configCacheCompleted():
							logger.notice("Event '%s' uses cached config and config caching is done", self.event.eventConfig.getId())
							config.setTemporaryConfigServiceUrls(['https://localhost:4441/rpc'])
						else:
							raise Exception(f"Event '{self.event.eventConfig.getId()}' uses cached config but config caching is not done")

					if self.event.eventConfig.getConfigFromService or self.event.eventConfig.processActions:
						if not self.isConfigServiceConnected():
							self.connectConfigService()

						if self.event.eventConfig.getConfigFromService:
							config.readConfigFile()
							self.getConfigFromService()
							if self.event.eventConfig.updateConfigFile:
								config.updateConfigFile()

						if self.event.eventConfig.processActions:
							if self.event.eventConfig.actionType == 'login':
								self.processUserLoginActions()
							else:
								self.processProductActionRequests()

							# After the installation of opsi-client-agent the opsiclientd.conf needs to be updated again
							if self.event.eventConfig.getConfigFromService:
								config.readConfigFile()
								self.getConfigFromService()
								if self.event.eventConfig.updateConfigFile:
									config.updateConfigFile()

				finally:
					self._messageSubject.setMessage("")
					if self.event.eventConfig.writeLogToService:
						try:
							self.writeLogToService()
						except Exception as err: # pylint: disable=broad-except
							logger.error(err, exc_info=True)

					try:
						self.disconnectConfigService()
					except Exception as err: # pylint: disable=broad-except
						logger.error(err, exc_info=True)

					config.setTemporaryConfigServiceUrls([])

					if self.event.eventConfig.postSyncConfigToServer:
						self.setStatusMessage( _("Syncing config to server") )
						self.opsiclientd.getCacheService().syncConfigToServer(waitForEnding = True)
						self.setStatusMessage( _("Sync completed") )
					if self.event.eventConfig.postSyncConfigFromServer:
						self.setStatusMessage( _("Syncing config from server") )
						self.opsiclientd.getCacheService().syncConfigFromServer(waitForEnding = self.isShutdownRequested() or self.isRebootRequested())
						self.setStatusMessage( _("Sync completed") )

					if self.event.eventConfig.postEventCommand:
						logger.notice("Running post event command '%s'",
							self.event.eventConfig.postEventCommand
						)
						encoding = "cp850" if RUNNING_ON_WINDOWS else "utf-8"
						try:
							output = subprocess.check_output(
								self.event.eventConfig.postEventCommand,
								shell=True,
								stderr=subprocess.STDOUT
							)
							logger.info("Post event command '%s' output: %s",
								self.event.eventConfig.postEventCommand,
								output.decode(encoding, errors="replace")
							)
						except subprocess.CalledProcessError as err:
							logger.error("Post event command '%s' returned exit code %s: %s",
								self.event.eventConfig.postEventCommand,
								err.returncode,
								err.output.decode(encoding, errors="replace")
							)

					self.processShutdownRequests()

					if self.opsiclientd.isShutdownTriggered():
						self.setStatusMessage(_("Shutting down machine"))
					elif self.opsiclientd.isRebootTriggered():
						self.setStatusMessage(_("Rebooting machine"))
					else:
						self.setStatusMessage(_("Unblocking login"))

					if not self.opsiclientd.isRebootTriggered() and not self.opsiclientd.isShutdownTriggered():
						# TODO: Not needed with new opsi-login-blocker (>= 4.2.0.0), remove when released
						self.opsiclientd.setBlockLogin(False)

					self.setStatusMessage("")
					self.stopNotificationServer()
					if notifierPids:
						try:
							time.sleep(3)
							for notifierPid in notifierPids:
								System.terminateProcess(processId=notifierPid)
						except Exception: # pylint: disable=broad-except
							pass
			except Exception as err: # pylint: disable=broad-except
				logger.error("Failed to process event %s: %s", self.event, err, exc_info=True)
				timeline.addEvent(
					title=f"Failed to process event {self.event.eventConfig.getName()}",
					description=f"Failed to process event {self.event}: {err}",
					category="event_processing",
					isError=True
				)
				self.opsiclientd.setBlockLogin(False)

			self.running = False
			logger.notice(
				"============= EventProcessingThread for event '%s' ended =============",
				self.event.eventConfig.getId()
			)
			if timelineEventId:
				timeline.setEventEnd(eventId = timelineEventId)
