# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
Basic opsiclientd implementation. This is abstract in some parts that
should be overridden in the concrete implementation for an OS.
"""

from contextlib import contextmanager
import os
import sys
import threading
import time
import tempfile
import platform
import subprocess
import urllib.request
import shutil
import psutil

from OPSI import System
from OPSI.Types import forceBool, forceInt, forceUnicode
from OPSI.Util import randomString
from OPSI.Util.Message import MessageSubject, ChoiceSubject, NotificationServer
from OPSI import __version__ as python_opsi_version

from opsicommon.logging import logger, log_context
from opsicommon.system import ensure_not_already_running

from opsiclientd import __version__, config, check_signature
from opsiclientd.ControlPipe import ControlPipeFactory
from opsiclientd.ControlServer import ControlServer
from opsiclientd.Events.Basic import EventListener
from opsiclientd.Events.DaemonShutdown import DaemonShutdownEventGenerator
from opsiclientd.Events.DaemonStartup import DaemonStartupEventGenerator
from opsiclientd.Events.Panic import PanicEvent
from opsiclientd.Events.Utilities.Factories import EventGeneratorFactory
from opsiclientd.Events.Utilities.Generators import createEventGenerators, getEventGenerators
from opsiclientd.EventProcessing import EventProcessingThread
from opsiclientd.Localization import _
from opsiclientd.State import State
from opsiclientd.Timeline import Timeline
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS
from opsiclientd.setup import setup

try:
	from opsiclientd.nonfree import __fullversion__
except ImportError:
	__fullversion__ = False

if RUNNING_ON_WINDOWS:
	from opsiclientd.Events.Windows.GUIStartup import (
		GUIStartupEventConfig, GUIStartupEventGenerator
	)

timeline = Timeline()
state = State()

class Opsiclientd(EventListener, threading.Thread):  # pylint: disable=too-many-instance-attributes,too-many-public-methods
	def __init__(self):
		logger.debug("Opsiclient initiating")

		EventListener.__init__(self)
		threading.Thread.__init__(self)

		self._startupTime = time.time()
		self._running = False
		self._eventProcessingThreads = []
		self._eventProcessingThreadsLock = threading.Lock()
		self._blockLogin = True
		self._currentActiveDesktopName = {}

		self._isRebootTriggered = False
		self._isShutdownTriggered = False

		self._actionProcessorUserName = ''
		self._actionProcessorUserPassword = ''

		self._statusApplicationProcess = None
		self._blockLoginNotifierPid = None

		self._popupNotificationServer = None
		self._popupNotificationLock = threading.Lock()

		self._blockLoginEventId = None
		self._opsiclientdRunningEventId = None

		self._stopEvent = threading.Event()
		self._stopEvent.clear()

		self._cacheService = None
		self._controlPipe = None

		self._selfUpdating = False

		self._argv = list(sys.argv)
		self._argv[0] = os.path.abspath(self._argv[0])

	def self_update_from_url(self, url):
		logger.notice("Self-update from url: %s", url)
		filename = url.split('/')[-1]
		with tempfile.TemporaryDirectory() as tmpdir:
			filename = os.path.join(tmpdir, filename)
			if url.startswith("file://"):
				src = url[7:]
				if RUNNING_ON_WINDOWS:
					src = src.lstrip('/').replace('/', '\\')
				shutil.copy(src, filename)
			else:
				with urllib.request.urlopen(url) as response:
					with open(filename, 'wb') as file:
						file.write(response.read())
			self.self_update_from_file(filename)

	def self_update_from_file(self, filename):
		logger.notice("Self-update from file %s", filename)

		test_file = "base_library.zip"
		inst_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
		if not os.path.exists(os.path.join(inst_dir, test_file)):
			raise RuntimeError(f"File not found: {os.path.join(inst_dir, test_file)}")

		if self._selfUpdating:
			raise RuntimeError("Self-update already running")
		self._selfUpdating = True
		try:
			with tempfile.TemporaryDirectory() as tmpdir:
				destination = os.path.join(tmpdir, "content")
				shutil.unpack_archive(filename=filename, extract_dir=destination)

				bin_dir = destination
				if not os.path.exists(os.path.join(bin_dir, test_file)):
					bin_dir = None
					for fn in os.listdir(destination):
						if os.path.exists(os.path.join(destination, fn, test_file)):
							bin_dir = os.path.join(destination, fn)
							break
				if not bin_dir:
					raise RuntimeError("Invalid archive")

				try:
					check_signature(bin_dir)
				except Exception as err: # pylint: disable=broad-except
					logger.error("Could not verify signature!\n%s", err, exc_info=True)
					logger.error("Not performing self_update.")
					raise RuntimeError("Invalid signature") from err

				binary = os.path.join(bin_dir, os.path.basename(self._argv[0]))

				logger.info("Testing new binary: %s", binary)
				out = subprocess.check_output([binary, "--version"])
				logger.info(out)

				move_dir = inst_dir + "_old"
				logger.info("Moving current installation dir '%s' to '%s'", inst_dir, move_dir)
				if os.path.exists(move_dir):
					shutil.rmtree(move_dir)
				os.rename(inst_dir, move_dir)

				logger.info("Installing '%s' into '%s'", bin_dir, inst_dir)
				shutil.copytree(bin_dir, inst_dir)

				self.restart(3)
		finally:
			self._selfUpdating = False

	def restart(self, waitSeconds=0):
		def _restart(waitSeconds=0):
			time.sleep(waitSeconds)
			timeline.addEvent(title = "opsiclientd restart", category = "system")
			try:
				logger.notice("Writing restart marker %s", config.restart_marker)
				open(config.restart_marker, "w").close()
			except Exception as err: # pylint: disable=broad-except
				logger.error(err)
			logger.notice("Executing: %s", self._argv)
			os.chdir(os.path.dirname(self._argv[0]))
			os.execvp(self._argv[0], self._argv)
		logger.notice("Will restart in %d seconds", waitSeconds)
		threading.Thread(target=_restart, args=(waitSeconds, )).start()

	def setBlockLogin(self, blockLogin): # pylint: disable=too-many-branches
		blockLogin = forceBool(blockLogin)
		changed = self._blockLogin != blockLogin
		self._blockLogin = blockLogin
		logger.notice("Block login now set to '%s'", self._blockLogin)

		if self._blockLogin:
			if not self._blockLoginEventId:
				self._blockLoginEventId = timeline.addEvent(
					title="Blocking login",
					description="User login blocked",
					category="block_login",
					durationEvent=True
				)

			if not self._blockLoginNotifierPid and config.get('global', 'block_login_notifier'):
				if RUNNING_ON_WINDOWS:
					logger.info("Starting block login notifier app")
					# Start block login notifier on physical console
					sessionId = System.getActiveConsoleSessionId()
					while True:
						try:
							self._blockLoginNotifierPid = System.runCommandInSession(
									command=config.get('global', 'block_login_notifier'),
									sessionId=sessionId,
									desktop='winlogon',
									waitForProcessEnding=False
							)[2]
							break
						except Exception as err: # pylint: disable=broad-except
							logger.error("Failed to start block login notifier app: %s", err)
							break
		else:
			if self._blockLoginEventId:
				timeline.setEventEnd(eventId=self._blockLoginEventId)
				self._blockLoginEventId = None

			if self._blockLoginNotifierPid:
				try:
					logger.info("Terminating block login notifier app (pid %s)", self._blockLoginNotifierPid)
					System.terminateProcess(processId=self._blockLoginNotifierPid)
				except Exception as err: # pylint: disable=broad-except
					logger.warning("Failed to terminate block login notifier app: %s", err)
				self._blockLoginNotifierPid = None

		if changed and self._controlPipe:
			try:
				self._controlPipe.executeRpc("blockLogin", self._blockLogin)
			except Exception as rpc_error: # pylint: disable=broad-except
				logger.debug(rpc_error)

	def loginUser(self, username, password):
		raise NotImplementedError(f"Not implemented on {platform.system()}")

	def isRunning(self):
		return self._running

	def is_stopping(self):
		return self._stopEvent.is_set()

	def waitForGUI(self, timeout=None):
		waiter = WaitForGUI(self)
		waiter.wait(timeout or None)

	def createActionProcessorUser(self, recreate=True):
		if not config.get('action_processor', 'create_user'):
			return

		run_as_user = config.get('action_processor', 'run_as_user')
		if run_as_user.lower() == 'system':
			self._actionProcessorUserName = ''
			self._actionProcessorUserPassword = ''
			return

		if '\\' in run_as_user:
			logger.warning("Ignoring domain part of user to run action processor '%s'", run_as_user)
			run_as_user = run_as_user.split('\\', -1)

		if not recreate and self._actionProcessorUserName and self._actionProcessorUserPassword and System.existsUser(username=run_as_user):
			return

		self._actionProcessorUserName = run_as_user
		logger.notice("Creating local user '%s'" % run_as_user)

		self._actionProcessorUserPassword = '$!?' + str(randomString(16)) + '!/%'
		logger.addConfidentialString(self._actionProcessorUserPassword)

		if System.existsUser(username=run_as_user):
			System.deleteUser(username=run_as_user)
		System.createUser(username=run_as_user, password=self._actionProcessorUserPassword, groups=[System.getAdminGroupName()])

	def deleteActionProcessorUser(self):
		if not config.get('action_processor', 'delete_user'):
			return

		if not self._actionProcessorUserName:
			return

		if not System.existsUser(username=self._actionProcessorUserName):
			return

		logger.notice("Deleting local user '%s'", self._actionProcessorUserName)
		System.deleteUser(username=self._actionProcessorUserName)
		self._actionProcessorUserName = ''
		self._actionProcessorUserPassword = ''

	def run(self):
		with log_context({'instance' : 'opsiclientd'}):
			try:
				self._run()
			except Exception as err:  # pylint: disable=broad-except
				logger.error(err, exc_info=True)

	def _run(self):  # pylint: disable=too-many-statements,too-many-branches
		ensure_not_already_running("opsiclientd")
		self._running = True
		self._opsiclientdRunningEventId = None

		try:
			state.start()
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to start state: %s", err, exc_info=True)
		try:
			timeline.start()
		except Exception as err:  # pylint: disable=broad-except
			logger.error("Failed to start timeline: %s", err, exc_info=True)

		config.readConfigFile()
		config.check_restart_marker()

		setup(full=False)

		@contextmanager
		def getControlPipe():
			logger.notice("Starting control pipe")
			try:
				self._controlPipe = ControlPipeFactory(self)
				self._controlPipe.daemon = True
				self._controlPipe.start()
				logger.notice("Control pipe started")
				yield
			except Exception as err: # pylint: disable=broad-except
				logger.error("Failed to start control pipe: %s", err, exc_info=True)
				raise
			finally:
				logger.info("Stopping control pipe")
				try:
					self._controlPipe.stop()
					self._controlPipe.join(2)
					logger.info("Control pipe stopped")
				except (NameError, RuntimeError) as stopError:
					logger.debug("Stopping controlPipe failed: %s", stopError)

		@contextmanager
		def getControlServer():
			logger.notice("Starting control server")
			control_server = None
			try:
				control_server = ControlServer(
					opsiclientd=self,
					httpsPort=config.get('control_server', 'port'),
					sslServerKeyFile=config.get('control_server', 'ssl_server_key_file'),
					sslServerCertFile=config.get('control_server', 'ssl_server_cert_file'),
					staticDir=config.get('control_server', 'static_dir')
				)
				logger.debug("Current control server: %s", control_server)
				control_server.start()
				logger.notice("Control server started")

				self._stopEvent.wait(1)
				if self._stopEvent.is_set():
					# Probably a failure during binding to port.
					raise RuntimeError("Received stop signal.")

				yield
			except Exception as err: # pylint: disable=broad-except
				logger.error("Failed to start control server: %s", err, exc_info=True)
				raise err
			finally:
				if control_server:
					logger.info("Stopping control server")
					try:
						control_server.stop()
						control_server.join(2)
						logger.info("Control server stopped")
					except (NameError, RuntimeError) as stopError:
						logger.debug("Stopping controlServer failed: %s", stopError)

		@contextmanager
		def getCacheService():
			cache_service = None
			try:
				logger.notice("Starting cache service")
				from opsiclientd.nonfree.CacheService import CacheService # pylint: disable=import-outside-toplevel
				cache_service = CacheService(opsiclientd=self)
				cache_service.start()
				logger.notice("Cache service started")
				yield cache_service
			except Exception as err: # pylint: disable=broad-except
				logger.error("Failed to start cache service: %s", err, exc_info=True)
				yield None
			finally:
				if cache_service:
					logger.info("Stopping cache service")
					try:
						cache_service.stop()
						cache_service.join(2)
						logger.info("Cache service stopped")
					except (NameError, RuntimeError) as stop_err:
						logger.debug("Failed to stop cache service: %s", stop_err)

		@contextmanager
		def getEventGeneratorContext():
			logger.debug("Creating event generators")
			createEventGenerators(self)

			for eventGenerator in getEventGenerators():
				eventGenerator.addEventListener(self)
				eventGenerator.start()
				logger.info("Event generator '%s' started", eventGenerator)

			try:
				yield
			finally:
				for eventGenerator in getEventGenerators():
					logger.info("Stopping event generator %s", eventGenerator)
					eventGenerator.stop()
					eventGenerator.join(2)
					logger.info("Event generator %s stopped", eventGenerator)

		@contextmanager
		def getDaemonLoopingContext():
			with getEventGeneratorContext():
				for event_generator in getEventGenerators(generatorClass=DaemonStartupEventGenerator):
					event_generator.createAndFireEvent()

				if RUNNING_ON_WINDOWS and getEventGenerators(generatorClass=GUIStartupEventGenerator):
					# Wait until gui starts up
					logger.notice("Waiting for gui startup (timeout: %d seconds)", config.get('global', 'wait_for_gui_timeout'))
					self.waitForGUI(timeout=config.get('global', 'wait_for_gui_timeout'))
					logger.notice("Done waiting for GUI")

					# Wait some more seconds for events to fire
					time.sleep(5)

				try:
					yield
				finally:
					for event_generator in getEventGenerators(generatorClass=DaemonShutdownEventGenerator):
						logger.info("Create and fire shutdown event generator %s", event_generator)
						event_generator.createAndFireEvent()

		try:
			parent = psutil.Process(os.getpid()).parent()
			parent_name = parent.name() if parent else None
			event_title = f"Opsiclientd {__version__} [python-opsi={python_opsi_version}]" \
				f" ({'full' if __fullversion__ else 'open'})" \
				f" running on {platform.system()}"
			logger.essential(event_title)
			event_description = f"Parent process: {parent_name}\n"
			logger.essential(f"Parent process: {parent_name}")
			event_description += f"Commandline: {' '.join(sys.argv)}\n"
			logger.essential(f"Commandline: {' '.join(sys.argv)}")
			event_description += f"Working directory: {os.getcwd()}\n"
			logger.essential(f"Working directory: {os.getcwd()}")
			event_description += f"Using host id '{config.get('global', 'host_id')}'"
			logger.notice(f"Using host id '{config.get('global', 'host_id')}'")

			logger.debug("Environment: %s", os.environ)

			self.setBlockLogin(True)

			self._opsiclientdRunningEventId = timeline.addEvent(
				title=event_title,
				description=event_description,
				category="opsiclientd_running",
				durationEvent=True
			)

			with getControlPipe():
				with getControlServer():
					with getCacheService() as cacheService:
						self._cacheService = cacheService

						with getDaemonLoopingContext():
							if not self._eventProcessingThreads:
								logger.notice("No events processing, unblocking login")
								self.setBlockLogin(False)

							try:
								while not self._stopEvent.is_set():
									self._stopEvent.wait(1)
							finally:
								logger.notice("opsiclientd is going down")

								for ept in self._eventProcessingThreads:
									ept.stop()
								for ept in self._eventProcessingThreads:
									logger.info("Waiting for event processing thread %s", ept)
									ept.join(5)

								if self._opsiclientdRunningEventId:
									timeline.setEventEnd(self._opsiclientdRunningEventId)
								logger.info("Stopping timeline")
								timeline.stop()
		except Exception as err: # pylint: disable=broad-except
			if not self._stopEvent.is_set():
				logger.error(err, exc_info=True)
			self.setBlockLogin(False)
		finally:
			self._running = False
			for thread in threading.enumerate():
				logger.info("Runnning thread on main thread exit: %s", thread)

			logger.info("Exiting opsiclientd thread")

	def stop(self):
		logger.notice("Stopping %s", self)
		self._stopEvent.set()

	def getCacheService(self):
		if not self._cacheService:
			raise RuntimeError("Cache service not started")
		return self._cacheService

	def processEvent(self, event):
		logger.notice("Processing event %s", event)
		eventProcessingThread = None
		with self._eventProcessingThreadsLock:
			description = f"Event {event.eventConfig.getId()} occurred\n"
			description += "Config:\n"
			_config = event.eventConfig.getConfig()
			configKeys = list(_config.keys())
			configKeys.sort()
			for configKey in configKeys:
				description += f"{configKey}: {_config[configKey]}\n"
			timeline.addEvent(
				title=f"Event {event.eventConfig.getName()}",
				description=description,
				category="event_occurrence"
			)

			eventProcessingThread = EventProcessingThread(self, event)

			# Always process panic events
			if not isinstance(event, PanicEvent):
				for ept in self._eventProcessingThreads:
					if event.eventConfig.actionType != 'login' and ept.event.eventConfig.actionType != 'login':
						logger.notice("Already processing an other (non login) event: %s", ept.event.eventConfig.getId())
						return

					if event.eventConfig.actionType == 'login' and ept.event.eventConfig.actionType == 'login':
						if ept.getSessionId() == eventProcessingThread.getSessionId():
							logger.notice("Already processing login event '%s' in session %s",
								ept.event.eventConfig.getName(), eventProcessingThread.getSessionId()
							)
							return
			self.createActionProcessorUser(recreate=False)
			self._eventProcessingThreads.append(eventProcessingThread)

		try:
			eventProcessingThread.start()
			eventProcessingThread.join()
			logger.notice("Done processing event %s", event)
		finally:
			with self._eventProcessingThreadsLock:
				self._eventProcessingThreads.remove(eventProcessingThread)

				if not self._eventProcessingThreads:
					try:
						self.deleteActionProcessorUser()
					except Exception as err: # pylint: disable=broad-except
						logger.warning(err)

	def getEventProcessingThreads(self):
		return self._eventProcessingThreads

	def getEventProcessingThread(self, sessionId):
		for ept in self._eventProcessingThreads:
			if int(ept.getSessionId()) == int(sessionId):
				return ept
		raise Exception(f"Event processing thread for session {sessionId} not found")

	def processProductActionRequests(self, event): # pylint: disable=unused-argument,no-self-use
		logger.error("processProductActionRequests not implemented")

	def getCurrentActiveDesktopName(self, sessionId=None):
		if not RUNNING_ON_WINDOWS:
			return None

		if not ('opsiclientd_rpc' in config.getDict() and 'command' in config.getDict()['opsiclientd_rpc']):
			raise Exception("opsiclientd_rpc command not defined")

		if sessionId is None:
			sessionId = System.getActiveSessionId()
			if sessionId is None:
				sessionId = System.getActiveConsoleSessionId()

		rpc = f"setCurrentActiveDesktopName(\"{sessionId}\", System.getActiveDesktopName())"
		cmd = '%s "%s"' % (config.get('opsiclientd_rpc', 'command'), rpc.replace('"', '\\"'))
		try:
			System.runCommandInSession(
				command=cmd,
				sessionId=sessionId,
				desktop="winlogon",
				waitForProcessEnding=True,
				timeoutSeconds=60,
				noWindow=True
			)
		except Exception as err: # pylint: disable=broad-except
			logger.error(err)

		desktop = self._currentActiveDesktopName.get(sessionId)
		if not desktop:
			logger.warning("Failed to get current active desktop name for session %s, using 'default'", sessionId)
			desktop = "default"
			self._currentActiveDesktopName[sessionId] = desktop
		logger.debug("Returning current active dektop name '%s' for session %s", desktop, sessionId)
		return desktop

	def switchDesktop(self, desktop, sessionId=None): # pylint: disable=no-self-use
		if not ('opsiclientd_rpc' in config.getDict() and 'command' in config.getDict()['opsiclientd_rpc']):
			raise Exception("opsiclientd_rpc command not defined")

		desktop = forceUnicode(desktop)
		if sessionId is None:
			sessionId = System.getActiveSessionId()
			if sessionId is None:
				sessionId = System.getActiveConsoleSessionId()
		sessionId = forceInt(sessionId)

		rpc = f"noop(System.switchDesktop('{desktop}'))"
		cmd = '%s "%s"' % (config.get('opsiclientd_rpc', 'command'), rpc)

		try:
			System.runCommandInSession(
				command=cmd,
				sessionId=sessionId,
				desktop=desktop,
				waitForProcessEnding=True,
				timeoutSeconds=60,
				noWindow=True
			)
		except Exception as err: # pylint: disable=broad-except
			logger.error(err)

	def systemShutdownInitiated(self):
		if not self.isRebootTriggered() and not self.isShutdownTriggered():
			# This shutdown was triggered by someone else
			# Reset shutdown/reboot requests to avoid reboot/shutdown on next boot
			logger.notice("Someone triggered a reboot or a shutdown => clearing reboot request")
			self.clearRebootRequest()

	def rebootMachine(self, waitSeconds=3):
		self._isRebootTriggered = True
		if self._controlPipe:
			try:
				self._controlPipe.executeRpc("rebootTriggered", True)
			except Exception as err: # pylint: disable=broad-except
				logger.debug(err)
		self.clearRebootRequest()
		System.reboot(wait=waitSeconds)

	def shutdownMachine(self, waitSeconds=3):
		self._isShutdownTriggered = True
		if self._controlPipe:
			try:
				self._controlPipe.executeRpc("shutdownTriggered", True)
			except Exception as err: # pylint: disable=broad-except
				logger.debug(err)
		self.clearShutdownRequest()
		System.shutdown(wait=waitSeconds)

	def isRebootTriggered(self):
		if self._isRebootTriggered:
			return True
		return False

	def isShutdownTriggered(self):
		if self._isShutdownTriggered:
			return True
		return False

	def clearRebootRequest(self): # pylint: disable=no-self-use
		pass

	def clearShutdownRequest(self): # pylint: disable=no-self-use
		pass

	def isRebootRequested(self): # pylint: disable=no-self-use
		return False

	def isShutdownRequested(self): # pylint: disable=no-self-use
		return False

	def isInstallationPending(self): # pylint: disable=no-self-use
		return state.get('installation_pending', False)

	def showPopup(self, message, mode='prepend', addTimestamp=True): # pylint: disable=too-many-branches,too-many-statements
		if mode not in ('prepend', 'append', 'replace'):
			mode = 'prepend'
		port = config.get('notification_server', 'popup_port')
		if not port:
			raise Exception('notification_server.popup_port not defined')

		notifierCommand = config.get('opsiclientd_notifier', 'command')
		if not notifierCommand:
			raise Exception('opsiclientd_notifier.command not defined')
		notifierCommand += " -s %s" % os.path.join("notifier", "popup.ini")

		if addTimestamp:
			message = "=== " + time.strftime("%Y-%m-%d %H:%M:%S") + " ===\n" + message

		self._popupNotificationLock.acquire()
		try: # pylint: disable=too-many-nested-blocks
			if (
					mode in ('prepend', 'append') and
					self._popupNotificationServer and
					self._popupNotificationServer.isListening()
			):
				# Already runnning
				try:
					for subject in self._popupNotificationServer.getSubjects():
						if subject.getId() == 'message':
							if mode == 'prepend':
								message = message + "\n\n" + subject.getMessage()
							else:
								message = subject.getMessage() + "\n\n" + message
							break
				except Exception as err: # pylint: disable=broad-except
					logger.warning(err, exc_info=True)

			self.hidePopup()

			popupSubject = MessageSubject(id='message')
			choiceSubject = ChoiceSubject(id='choice')
			popupSubject.setMessage(message)

			logger.notice("Starting popup message notification server on port %d", port)
			try:
				self._popupNotificationServer = NotificationServer(
					address="127.0.0.1",
					start_port=port,
					subjects=[popupSubject, choiceSubject]
				)
				self._popupNotificationServer.daemon = True
				with log_context({'instance' : 'popup notification server'}):
					if not self._popupNotificationServer.start_and_wait(timeout=30):
						raise Exception("Timed out while waiting for notification server")
			except Exception as err: # pylint: disable=broad-except
				logger.error("Failed to start notification server: %s", err)
				raise

			notifierCommand = notifierCommand.replace('%port%', str(self._popupNotificationServer.port)).replace('%id%', "popup")

			choiceSubject.setChoices([_('Close')])
			choiceSubject.setCallbacks([self.popupCloseCallback])

			sessionIds = System.getActiveSessionIds()
			if not sessionIds:
				sessionIds = [System.getActiveConsoleSessionId()]
			for sessionId in sessionIds:
				desktops = [None]
				if RUNNING_ON_WINDOWS:
					desktops = ["default", "winlogon"]
				for desktop in desktops:
					try:
						System.runCommandInSession(
							command=notifierCommand,
							sessionId=sessionId,
							desktop=desktop,
							waitForProcessEnding=False
					)
					except Exception as err: # pylint: disable=broad-except
						logger.error(
							"Failed to start popup message notifier app in session %s on desktop %s: %s",
							sessionId, desktop, err
						)
		finally:
			self._popupNotificationLock.release()

	def hidePopup(self):
		if self._popupNotificationServer:
			try:
				logger.info("Stopping popup message notification server")

				self._popupNotificationServer.stop(stopReactor=False)
			except Exception as err: # pylint: disable=broad-except
				logger.error("Failed to stop popup notification server: %s", err)

	def popupCloseCallback(self, choiceSubject): # pylint: disable=unused-argument
		self.hidePopup()


class WaitForGUI(EventListener):
	def __init__(self, opsiclientd): # pylint: disable=super-init-not-called
		self._guiStarted = threading.Event()
		ec = GUIStartupEventConfig("wait_for_gui")
		eventGenerator = EventGeneratorFactory(opsiclientd, ec)
		eventGenerator.addEventConfig(ec)
		eventGenerator.addEventListener(self)
		eventGenerator.start()

	def processEvent(self, event):
		logger.info("GUI started")
		self._guiStarted.set()

	def wait(self, timeout=None):
		self._guiStarted.wait(timeout)
		if not self._guiStarted.isSet():
			logger.warning("Timed out after %d seconds while waiting for GUI", timeout)
