# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Basic opsiclientd implementation. This is abstract in some parts that
should be overridden in the concrete implementation for an OS.
"""

import datetime
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import List

import psutil
from OPSI import System
from OPSI import __version__ as python_opsi_version
from OPSI.Types import forceBool, forceInt, forceUnicode
from OPSI.Util import randomString
from OPSI.Util.Message import ChoiceSubject, MessageSubject, NotificationServer
from opsicommon.logging import log_context, logger, secret_filter
from opsicommon.system import ensure_not_already_running

from opsiclientd import __version__, check_signature, config
from opsiclientd.ControlPipe import ControlPipeFactory
from opsiclientd.ControlServer import ControlServer
from opsiclientd.EventProcessing import EventProcessingThread
from opsiclientd.Events.Basic import CannotCancelEventError, EventListener
from opsiclientd.Events.DaemonShutdown import DaemonShutdownEventGenerator
from opsiclientd.Events.DaemonStartup import DaemonStartupEventGenerator
from opsiclientd.Events.GUIStartup import (
	GUIStartupEventConfig,
	GUIStartupEventGenerator,
)
from opsiclientd.Events.Panic import PanicEvent
from opsiclientd.Events.Utilities.Factories import EventGeneratorFactory
from opsiclientd.Events.Utilities.Generators import (
	createEventGenerators,
	getEventGenerators,
)
from opsiclientd.Localization import _
from opsiclientd.setup import setup
from opsiclientd.State import State
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS
from opsiclientd.Timeline import Timeline

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
		self.eventLock = threading.Lock()
		self._eptListLock = threading.Lock()
		self._blockLogin = True
		self._currentActiveDesktopName = {}
		self._gui_waiter = None

		self._isRebootTriggered = False
		self._isShutdownTriggered = False

		self._actionProcessorUserName = ""
		self._actionProcessorUserPassword = ""

		self._statusApplicationProcess = None
		self._blockLoginNotifierPid = None

		self._popupNotificationServer = None
		self._popupNotificationLock = threading.Lock()
		self._popupClosingThread = None

		self._blockLoginEventId = None
		self._opsiclientdRunningEventId = None

		self._stopEvent = threading.Event()
		self._stopEvent.clear()

		self._cacheService = None
		self._controlPipe = None
		self._controlServer = None

		self._selfUpdating = False

		self._argv = list(sys.argv)
		self._argv[0] = os.path.abspath(self._argv[0])

	def self_update_from_url(self, url):
		logger.notice("Self-update from url: %s", url)
		filename = url.split("/")[-1]
		with tempfile.TemporaryDirectory() as tmpdir:
			filename = os.path.join(tmpdir, filename)
			if url.startswith("file://"):
				src = url[7:]
				if RUNNING_ON_WINDOWS:
					src = src.lstrip("/").replace("/", "\\")
				shutil.copy(src, filename)
			else:
				with urllib.request.urlopen(url) as response:
					with open(filename, "wb") as file:
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
				except Exception as err:  # pylint: disable=broad-except
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
			timeline.addEvent(title="opsiclientd restart", category="system")
			try:
				if not os.path.exists(config.restart_marker):
					logger.notice("Writing restart marker %s", config.restart_marker)
					with open(config.restart_marker, "w", encoding="utf-8") as file:
						file.write("#")
			except Exception as err:  # pylint: disable=broad-except
				logger.error(err)

			if RUNNING_ON_WINDOWS:
				subprocess.Popen(  # pylint: disable=consider-using-with
					"net stop opsiclientd & net start opsiclientd",
					shell=True,
					creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
				)
			else:
				logger.notice("Executing: %s", self._argv)
				os.chdir(os.path.dirname(self._argv[0]))
				os.execvp(self._argv[0], self._argv)

		logger.notice("Will restart in %d seconds", waitSeconds)
		threading.Thread(target=_restart, args=(waitSeconds,)).start()

	def setBlockLogin(self, blockLogin, handleNotifier=True):  # pylint: disable=too-many-branches
		blockLogin = forceBool(blockLogin)
		changed = self._blockLogin != blockLogin
		self._blockLogin = blockLogin
		logger.notice("Block login now set to '%s'", self._blockLogin)

		if self._blockLogin:
			if not self._blockLoginEventId:
				self._blockLoginEventId = timeline.addEvent(
					title="Blocking login", description="User login blocked", category="block_login", durationEvent=True
				)

			if not self._blockLoginNotifierPid and config.get("global", "block_login_notifier"):
				if handleNotifier and RUNNING_ON_WINDOWS:
					logger.info("Starting block login notifier app")
					# Start block login notifier on physical console
					sessionId = System.getActiveConsoleSessionId()
					while True:
						try:
							self._blockLoginNotifierPid = System.runCommandInSession(
								command=config.get("global", "block_login_notifier"),
								sessionId=sessionId,
								desktop="winlogon",
								waitForProcessEnding=False,
							)[2]
							break
						except Exception as err:  # pylint: disable=broad-except
							logger.error("Failed to start block login notifier app: %s", err)
							break
		else:
			if self._blockLoginEventId:
				timeline.setEventEnd(eventId=self._blockLoginEventId)
				self._blockLoginEventId = None

			if handleNotifier and self._blockLoginNotifierPid:
				try:
					logger.info("Terminating block login notifier app (pid %s)", self._blockLoginNotifierPid)
					System.terminateProcess(processId=self._blockLoginNotifierPid)
				except Exception as err:  # pylint: disable=broad-except
					log = logger.warning
					if isinstance(err, OSError) and getattr(err, "errno", None) == 87:
						# Process already terminated
						log = logger.debug
					log("Failed to terminate block login notifier app: %s", err)
				self._blockLoginNotifierPid = None

		if changed and self._controlPipe:
			try:
				self._controlPipe.executeRpc("blockLogin", self._blockLogin)
			except Exception as rpc_error:  # pylint: disable=broad-except
				logger.debug(rpc_error)

	def loginUser(self, username, password):
		raise NotImplementedError(f"Not implemented on {platform.system()}")

	def isRunning(self):
		return self._running

	def is_stopping(self):
		return self._stopEvent.is_set()

	def waitForGUI(self, timeout=None):
		self._gui_waiter = WaitForGUI(self)
		self._gui_waiter.wait(timeout)
		self._gui_waiter = None

	def createActionProcessorUser(self, recreate=True):
		if not config.get("action_processor", "create_user"):
			return

		run_as_user = config.get("action_processor", "run_as_user")
		if run_as_user.lower() == "system":
			self._actionProcessorUserName = ""
			self._actionProcessorUserPassword = ""
			return

		if "\\" in run_as_user:
			logger.warning("Ignoring domain part of user to run action processor '%s'", run_as_user)
			run_as_user = run_as_user.split("\\", -1)

		if not recreate and self._actionProcessorUserName and self._actionProcessorUserPassword and System.existsUser(username=run_as_user):
			return

		self._actionProcessorUserName = run_as_user
		logger.notice(f"Creating local user '{run_as_user}'")

		self._actionProcessorUserPassword = "$!?" + str(randomString(16)) + "!/%"
		secret_filter.add_secrets(self._actionProcessorUserPassword)

		if System.existsUser(username=run_as_user):
			System.deleteUser(username=run_as_user)
		System.createUser(username=run_as_user, password=self._actionProcessorUserPassword, groups=[System.getAdminGroupName()])

	def deleteActionProcessorUser(self):
		if not config.get("action_processor", "delete_user"):
			return

		if not self._actionProcessorUserName:
			return

		if not System.existsUser(username=self._actionProcessorUserName):
			return

		logger.notice("Deleting local user '%s'", self._actionProcessorUserName)
		System.deleteUser(username=self._actionProcessorUserName)
		self._actionProcessorUserName = ""
		self._actionProcessorUserPassword = ""

	def run(self):
		with log_context({"instance": "opsiclientd"}):
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
			except Exception as err:  # pylint: disable=broad-except
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
			self._controlServer = None
			try:
				self._controlServer = ControlServer(
					opsiclientd=self,
					httpsPort=config.get("control_server", "port"),
					sslServerKeyFile=config.get("control_server", "ssl_server_key_file"),
					sslServerCertFile=config.get("control_server", "ssl_server_cert_file"),
					staticDir=config.get("control_server", "static_dir"),
				)
				logger.debug("Current control server: %s", self._controlServer)
				self._controlServer.start()
				logger.notice("Control server started")

				self._stopEvent.wait(1)
				if self._stopEvent.is_set():
					# Probably a failure during binding to port.
					raise RuntimeError("Received stop signal.")

				yield
			except Exception as err:  # pylint: disable=broad-except
				logger.error("Failed to start control server: %s", err, exc_info=True)
				raise err
			finally:
				if self._controlServer:
					logger.info("Stopping control server")
					try:
						self._controlServer.stop()
						self._controlServer.join(2)
						logger.info("Control server stopped")
					except (NameError, RuntimeError) as stopError:
						logger.debug("Stopping controlServer failed: %s", stopError)

		@contextmanager
		def getCacheService():
			cache_service = None
			try:
				logger.notice("Starting cache service")
				from opsiclientd.nonfree.CacheService import (  # pylint: disable=import-outside-toplevel
					CacheService,
				)

				cache_service = CacheService(opsiclientd=self)
				cache_service.start()
				logger.notice("Cache service started")
				yield cache_service
			except Exception as err:  # pylint: disable=broad-except
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
					try:
						event_generator.createAndFireEvent()
					except ValueError as err:
						logger.error("Unable to fire DaemonStartupEvent from %s: %s", event_generator, err, exc_info=True)

				if getEventGenerators(generatorClass=GUIStartupEventGenerator):
					# Wait until gui starts up
					logger.notice("Waiting for gui startup (timeout: %d seconds)", config.get("global", "wait_for_gui_timeout"))
					self.waitForGUI(timeout=config.get("global", "wait_for_gui_timeout"))
					if not self.is_stopping():
						logger.notice("Done waiting for GUI")
						# Wait some more seconds for events to fire
						time.sleep(5)

				try:
					yield
				finally:
					for event_generator in getEventGenerators(generatorClass=DaemonShutdownEventGenerator):
						logger.info("Create and fire shutdown event generator %s", event_generator)
						try:
							event_generator.createAndFireEvent()
						except ValueError as err:
							logger.error("Unable to fire DaemonStartupEvent from %s: %s", event_generator, err, exc_info=True)

		try:
			parent = psutil.Process(os.getpid()).parent()
			parent_name = parent.name() if parent else None
			event_title = f"Opsiclientd {__version__} [python-opsi={python_opsi_version}] running on {platform.platform()!r}"
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

			# Do not show block login notifier yet!
			self.setBlockLogin(True, handleNotifier=False)

			self._opsiclientdRunningEventId = timeline.addEvent(
				title=event_title, description=event_description, category="opsiclientd_running", durationEvent=True
			)

			with getControlPipe():
				with getControlServer():
					with getCacheService() as cacheService:
						self._cacheService = cacheService

						with getDaemonLoopingContext():
							with self._eptListLock:
								if not self._eventProcessingThreads:
									logger.notice("No events processing, unblocking login")
									self.setBlockLogin(False)

							try:
								while not self._stopEvent.is_set():
									self._stopEvent.wait(1)
							finally:
								logger.notice("opsiclientd is going down")
								with self._eptListLock:
									for ept in self._eventProcessingThreads:
										ept.stop()
									for ept in self._eventProcessingThreads:
										logger.info("Waiting for event processing thread %s", ept)
										ept.join(5)

								if self._opsiclientdRunningEventId:
									timeline.setEventEnd(self._opsiclientdRunningEventId)
								logger.info("Stopping timeline")
								timeline.stop()
		except Exception as err:  # pylint: disable=broad-except
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
		if self._gui_waiter:
			self._gui_waiter.stop()
		self._stopEvent.set()

	def getCacheService(self):
		if not self._cacheService:
			raise RuntimeError("Cache service not started")
		return self._cacheService

	def canProcessEvent(self, event, can_cancel=False):
		# Always process panic events
		if isinstance(event, PanicEvent):
			return True
		with self._eptListLock:
			for ept in self._eventProcessingThreads:
				if event.eventConfig.actionType != "login" and ept.event.eventConfig.actionType != "login":
					if not ept.is_cancelable():
						logger.notice("Already processing a non-cancelable (and non-login) event: %s", ept.event.eventConfig.getId())
						raise CannotCancelEventError(f"Already processing a non-cancelable (and non-login) event: {ept.event.eventConfig.getId()}")
					if not can_cancel:
						logger.notice(
							"Currently running event can only be canceled by manual action (ControlServer/Kiosk): %s",
							ept.event.eventConfig.getId(),
						)
						raise CannotCancelEventError(
							"Currently running event can only be canceled by manual action (ControlServer/Kiosk): "
							f"{ept.event.eventConfig.getId()}"
						)
				if event.eventConfig.actionType == "login" and ept.event.eventConfig.actionType == "login":
					eventProcessingThread = EventProcessingThread(self, event)
					if ept.getSessionId() == eventProcessingThread.getSessionId():
						logger.notice(
							"Already processing login event '%s' in session %s",
							ept.event.eventConfig.getName(),
							eventProcessingThread.getSessionId(),
						)
					raise ValueError(
						f"Already processing login event '{ept.event.eventConfig.getName()}' "
						f"in session {eventProcessingThread.getSessionId()}"
					)
		return True

	def cancelOthersAndWaitUntilReady(self):
		WAIT_SECONDS = 30
		with self._eptListLock:
			eptListCopy = self._eventProcessingThreads.copy()
			for ept in self._eventProcessingThreads:
				if ept.event.eventConfig.actionType != "login":
					# trying to cancel all non-login events - RuntimeError if impossible
					logger.notice("Canceling event processing thread %s (ocd)", ept)
					ept.cancel(no_lock=True)
			logger.trace("Waiting for cancellation to conclude")

		# Use copy to allow for epts to be removed from eptList
		for ept in eptListCopy:
			if ept.event.eventConfig.actionType != "login":
				logger.trace("Waiting for ending of ept %s (ocd)", ept)
				for _unused in range(WAIT_SECONDS):
					if not ept or not ept.running:
						break
					time.sleep(1)
				if ept and ept.running:
					raise ValueError(f"Event {ept.event.eventConfig.name} didn't stop after {WAIT_SECONDS} seconds - aborting")
				logger.debug("Successfully canceled event '%s' of type %s", ept.event.eventConfig.name, ept.event.eventConfig.actionType)

				try:
					cache_service = self.getCacheService()
					logger.debug("Got config_service with state: %s - marking dirty", cache_service.getConfigCacheState())
					# mark cache as dirty when bypassing cache mechanism for installation
					cache_service.setConfigCacheFaulty()
				except RuntimeError as err:
					logger.info("Could not mark config service cache dirty: %s", err, exc_info=True)

	def processEvent(self, event):
		logger.notice("Processing event %s", event)

		description = f"Event {event.eventConfig.getId()} occurred\n"
		description += "Config:\n"
		_config = event.eventConfig.getConfig()
		configKeys = list(_config.keys())
		configKeys.sort()
		for configKey in configKeys:
			description += f"{configKey}: {_config[configKey]}\n"

		logger.trace("check lock (ocd), currently %s -> locking if not True", self.eventLock.locked())
		# if triggered by Basic.py fire_event, lock is already acquired
		if not self.eventLock.locked():
			self.eventLock.acquire()  # pylint: disable=consider-using-with

		try:
			timeline.addEvent(title=f"Event {event.eventConfig.getName()}", description=description, category="event_occurrence")
			# if processEvent is called through Event.fireEvent(), this check is already done
			# self.canProcessEvent(event)
			# A user login event should not cancel running non-login Event
			if event.eventConfig.actionType != "login":
				self.cancelOthersAndWaitUntilReady()
		except (ValueError, RuntimeError) as err:
			# skipping execution if event cannot be created
			logger.warning("Could not start event: %s", err, exc_info=True)
			logger.trace("release lock (ocd cannot process event)")
			self.eventLock.release()
			return
		try:
			logger.debug("Creating new ept (ocd)")
			eventProcessingThread = EventProcessingThread(self, event)

			self.createActionProcessorUser(recreate=False)
			with self._eptListLock:
				self._eventProcessingThreads.append(eventProcessingThread)
		finally:
			logger.trace("release lock (ocd)")
			self.eventLock.release()

		try:
			eventProcessingThread.start()
			eventProcessingThread.join()
			logger.notice("Done processing event %s", event)
		finally:
			with self._eptListLock:
				self._eventProcessingThreads.remove(eventProcessingThread)

				if not self._eventProcessingThreads:
					try:
						self.deleteActionProcessorUser()
					except Exception as err:  # pylint: disable=broad-except
						logger.warning(err)

	def getEventProcessingThreads(self):
		with self._eptListLock:
			return self._eventProcessingThreads

	def getEventProcessingThread(self, sessionId):
		with self._eptListLock:
			for ept in self._eventProcessingThreads:
				if int(ept.getSessionId()) == int(sessionId):
					return ept
		raise Exception(f"Event processing thread for session {sessionId} not found")

	def processProductActionRequests(self, event):  # pylint: disable=unused-argument
		logger.error("processProductActionRequests not implemented")

	def getCurrentActiveDesktopName(self, sessionId=None):
		if not RUNNING_ON_WINDOWS:
			return None

		if not ("opsiclientd_rpc" in config.getDict() and "command" in config.getDict()["opsiclientd_rpc"]):
			raise Exception("opsiclientd_rpc command not defined")

		if sessionId is None:
			sessionId = System.getActiveSessionId()
			if sessionId is None:
				sessionId = System.getActiveConsoleSessionId()

		rpc = f'setCurrentActiveDesktopName("{sessionId}", System.getActiveDesktopName())'
		cmd = config.get("opsiclientd_rpc", "command") + ' "' + rpc.replace('"', '\\"') + '"'
		try:
			System.runCommandInSession(
				command=cmd, sessionId=sessionId, desktop="winlogon", waitForProcessEnding=True, timeoutSeconds=60, noWindow=True
			)
		except Exception as err:  # pylint: disable=broad-except
			logger.error(err)

		desktop = self._currentActiveDesktopName.get(sessionId)
		if not desktop:
			logger.warning("Failed to get current active desktop name for session %s, using 'default'", sessionId)
			desktop = "default"
			self._currentActiveDesktopName[sessionId] = desktop
		logger.debug("Returning current active dektop name '%s' for session %s", desktop, sessionId)
		return desktop

	def switchDesktop(self, desktop, sessionId=None):
		if not ("opsiclientd_rpc" in config.getDict() and "command" in config.getDict()["opsiclientd_rpc"]):
			raise Exception("opsiclientd_rpc command not defined")

		desktop = forceUnicode(desktop)
		if sessionId is None:
			sessionId = System.getActiveSessionId()
			if sessionId is None:
				sessionId = System.getActiveConsoleSessionId()
		sessionId = forceInt(sessionId)

		rpc = f"noop(System.switchDesktop('{desktop}'))"
		cmd = f'{config.get("opsiclientd_rpc", "command")} "{rpc}"'

		try:
			System.runCommandInSession(
				command=cmd, sessionId=sessionId, desktop=desktop, waitForProcessEnding=True, timeoutSeconds=60, noWindow=True
			)
		except Exception as err:  # pylint: disable=broad-except
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
			except Exception as err:  # pylint: disable=broad-except
				logger.debug(err)
		self.clearRebootRequest()
		System.reboot(wait=waitSeconds)

	def shutdownMachine(self, waitSeconds=3):
		self._isShutdownTriggered = True
		if self._controlPipe:
			try:
				self._controlPipe.executeRpc("shutdownTriggered", True)
			except Exception as err:  # pylint: disable=broad-except
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

	def clearRebootRequest(self):
		pass

	def clearShutdownRequest(self):
		pass

	def isRebootRequested(self):
		return False

	def isShutdownRequested(self):
		return False

	def isInstallationPending(self):
		return state.get("installation_pending", False)

	def showPopup(
		self, message, mode="prepend", addTimestamp=True, displaySeconds=0
	):  # pylint: disable=too-many-branches,too-many-statements, too-many-locals
		if mode not in ("prepend", "append", "replace"):
			mode = "prepend"
		port = config.get("notification_server", "popup_port")
		if not port:
			raise Exception("notification_server.popup_port not defined")

		notifierCommand = config.get("opsiclientd_notifier", "command")
		if not notifierCommand:
			raise Exception("opsiclientd_notifier.command not defined")
		notifierCommand = f'{notifierCommand} -s {os.path.join("notifier", "popup.ini")}'

		if addTimestamp:
			message = "=== " + time.strftime("%Y-%m-%d %H:%M:%S") + " ===\n" + message

		with self._popupNotificationLock:  # pylint: disable=too-many-nested-blocks
			if mode in ("prepend", "append") and self._popupNotificationServer and self._popupNotificationServer.isListening():
				# Already runnning
				try:
					for subject in self._popupNotificationServer.getSubjects():
						if subject.getId() == "message":
							if mode == "prepend":
								message = message + "\n\n" + subject.getMessage()
							else:
								message = subject.getMessage() + "\n\n" + message
							break
				except Exception as err:  # pylint: disable=broad-except
					logger.warning(err, exc_info=True)

			self.hidePopup()

			popupSubject = MessageSubject(id="message")
			choiceSubject = ChoiceSubject(id="choice")
			popupSubject.setMessage(message)

			logger.notice("Starting popup message notification server on port %d", port)
			try:
				self._popupNotificationServer = NotificationServer(
					address="127.0.0.1", start_port=port, subjects=[popupSubject, choiceSubject]
				)
				self._popupNotificationServer.daemon = True
				with log_context({"instance": "popup notification server"}):
					if not self._popupNotificationServer.start_and_wait(timeout=30):
						raise Exception("Timed out while waiting for notification server")
			except Exception as err:  # pylint: disable=broad-except
				logger.error("Failed to start notification server: %s", err)
				raise

			notifierCommand = notifierCommand.replace("%port%", str(self._popupNotificationServer.port)).replace("%id%", "popup")

			choiceSubject.setChoices([_("Close")])
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
							command=notifierCommand, sessionId=sessionId, desktop=desktop, waitForProcessEnding=False
						)
					except Exception as err:  # pylint: disable=broad-except
						logger.error("Failed to start popup message notifier app in session %s on desktop %s: %s", sessionId, desktop, err)

			class PopupClosingThread(threading.Thread):
				def __init__(self, opsiclientd, seconds):
					super().__init__()
					self.opsiclientd = opsiclientd
					self.seconds = seconds
					self.stopped = False

				def stop(self):
					self.stopped = True

				def run(self):
					while not self.stopped:
						time.sleep(1)
						if time.time() > self.seconds:
							break
					if not self.stopped:
						logger.debug("hiding popup window")
						self.opsiclientd.hidePopup()

			# last popup decides end time (even if unlimited)
			if self._popupClosingThread and self._popupClosingThread.is_alive():
				self._popupClosingThread.stop()
			if displaySeconds > 0:
				logger.debug("displaying popup for %s seconds", displaySeconds)
				self._popupClosingThread = PopupClosingThread(self, time.time() + displaySeconds)
				self._popupClosingThread.start()

	def hidePopup(self):
		if self._popupNotificationServer:
			try:
				logger.info("Stopping popup message notification server")

				self._popupNotificationServer.stop(stopReactor=False)
			except Exception as err:  # pylint: disable=broad-except
				logger.error("Failed to stop popup notification server: %s", err)

	def popupCloseCallback(self, choiceSubject):  # pylint: disable=unused-argument
		self.hidePopup()

	def collectLogfiles(self, types: List[str] = None, max_age_days: int = None, timeline_db: bool = True) -> str:
		now = datetime.datetime.now().timestamp()
		type_patterns = []
		if not types:
			type_patterns.append(re.compile(r".*\.log"))
		for stem_type in types:
			type_patterns.append(re.compile(rf"{stem_type}[_0-9]*\.log"))

		def collect_matching_files(path: Path, result_path: Path, patterns: List[re.Pattern], max_age_days: int) -> None:
			for content in path.iterdir():
				if content.is_file() and any((re.match(pattern, content.name) for pattern in patterns)):
					if not max_age_days or now - content.lstat().st_mtime < int(max_age_days) * 3600 * 24:
						if not result_path.is_dir():
							result_path.mkdir()
						shutil.copy2(content, result_path)  # preserve metadata

				if content.is_dir():
					collect_matching_files(content, result_path / content.name, patterns, max_age_days)

		filename = f"logs-{config.get('global', 'host_id')}-{datetime.datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')}"
		outfile = Path(config.get("control_server", "files_dir")) / filename
		compression = "zip"
		with tempfile.TemporaryDirectory() as tempdir:
			tempdir_path = Path(tempdir) / filename
			tempdir_path.mkdir()
			logger.info("Collecting log files to %s", tempdir_path)
			collect_matching_files(Path(config.get("global", "log_dir")), tempdir_path, type_patterns, max_age_days)
			if timeline_db:
				db_path = Path(config.get('global', 'timeline_db'))
				if db_path.exists():
					shutil.copy2(db_path, tempdir_path)
			logger.info("Writing zip archive %s", outfile)
			shutil.make_archive(str(outfile), compression, root_dir=str(tempdir_path.parent), base_dir=tempdir_path.name)
		return outfile.parent / (outfile.name + f".{compression}")


class WaitForGUI(EventListener):
	def __init__(self, opsiclientd):  # pylint: disable=super-init-not-called
		self._opsiclientd = opsiclientd
		self._guiStarted = threading.Event()
		self._should_stop = False
		ec = GUIStartupEventConfig("wait_for_gui")
		eventGenerator = EventGeneratorFactory(self._opsiclientd, ec)
		eventGenerator.addEventConfig(ec)
		eventGenerator.addEventListener(self)
		eventGenerator.start()

	def stop(self):
		self._should_stop = True
		self._guiStarted.set()

	def processEvent(self, event):
		logger.trace("check lock (ocd), currently %s -> locking if not True", self._opsiclientd.eventLock.locked())
		# if triggered by Basic.py fire_event, lock is already acquired
		if not self._opsiclientd.eventLock.locked():
			self._opsiclientd.eventLock.acquire()
		try:
			logger.info("GUI started")
			self._guiStarted.set()
		finally:
			logger.trace("release lock (WaitForGUI)")
			self._opsiclientd.eventLock.release()

	def wait(self, timeout=None):
		self._guiStarted.wait(timeout)
		if self._should_stop:
			return
		if not self._guiStarted.is_set():
			logger.warning("Timed out after %d seconds while waiting for GUI", timeout)

	def canProcessEvent(self, event, can_cancel=False):  # pylint: disable=unused-argument
		# WaitForGUI should handle all Events
		return True
