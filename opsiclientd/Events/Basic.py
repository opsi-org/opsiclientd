# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Basic event building blocks.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import opsicommon.logging
from opsicommon.logging import get_logger
from opsicommon.types import forceList

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.State import State

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd

__all__ = ["Event", "EventGenerator", "EventListener"]

logger = get_logger()
state = State()


class CannotCancelEventError(RuntimeError):
	pass


class EventGenerator(threading.Thread):
	def __init__(self, opsiclientd: Opsiclientd, generatorConfig: EventConfig) -> None:
		threading.Thread.__init__(self, daemon=True, name=f"EventGenerator-{generatorConfig.getId()}")
		self._opsiclientd = opsiclientd
		self._generatorConfig = generatorConfig
		self._eventConfigs: list[EventConfig] = []
		self._eventListeners: list[EventListener] = []
		self._eventsOccured = 0
		self._threadId = None
		self._stopped = False
		self._event: threading.Event | None = None
		self._lastEventOccurence: float | None = None

	def __str__(self) -> str:
		return f"<{self.__class__.__name__} {self._generatorConfig.getId()}>"

	__repr__ = __str__

	def setEventConfigs(self, eventConfigs: list[EventConfig]) -> None:
		self._eventConfigs = forceList(eventConfigs)

	def addEventConfig(self, eventConfig: EventConfig) -> None:
		self._eventConfigs.append(eventConfig)

	def addEventListener(self, eventListener: EventListener) -> None:
		if not isinstance(eventListener, EventListener):
			raise TypeError(f"Failed to add event listener, got class {eventListener.__class__}, need class EventListener")

		if eventListener in self._eventListeners:
			return

		self._eventListeners.append(eventListener)

	def getEventConfig(self) -> EventConfig | None:
		logger.info("Testing preconditions of configs: %s", self._eventConfigs)
		actualPreconditions: dict[str, str] = {}
		actualConfig: EventConfig | None = None

		for pec in self._eventConfigs:
			p_state = {p: state.get(p, False) for p in pec.preconditions}
			if all(p_state.values()):
				logger.info("Preconditions %s for event config '%s' fulfilled (%r)", list(pec.preconditions), pec.getId(), p_state)
				if not actualConfig or (len(pec.preconditions.keys()) > len(actualPreconditions.keys())):
					actualPreconditions = pec.preconditions
					actualConfig = pec
			else:
				logger.info("Preconditions %s for event config '%s' not fulfilled (%r)", list(pec.preconditions), pec.getId(), p_state)

		return actualConfig

	def createAndFireEvent(self, eventInfo: dict[str, str | list[str]] | None = None, can_cancel: bool = False) -> None:
		self.fireEvent(self.createEvent(eventInfo), can_cancel=can_cancel)

	def createEvent(self, eventInfo: dict[str, str | list[str]] | None = None) -> Event | None:
		logger.debug("Creating event config from info: %s", eventInfo)
		eventConfig = self.getEventConfig()
		logger.debug("Event config: %s", eventConfig)
		if not eventConfig:
			return None

		return Event(eventConfig=eventConfig, eventInfo=eventInfo)

	def initialize(self) -> None:
		pass

	def getNextEvent(self) -> Event | None:
		self._event = threading.Event()
		logger.debug(
			"getNextEvent: eventsOccured=%d, startInterval=%d, interval=%d",
			self._eventsOccured,
			self._generatorConfig.startInterval,
			self._generatorConfig.interval,
		)
		if self._eventsOccured == 0 and self._generatorConfig.startInterval > 0:
			logger.debug("Waiting for start interval %d", self._generatorConfig.startInterval)
			self._event.wait(self._generatorConfig.startInterval)
			if self._stopped:
				return None
			return self.createEvent()
		if self._generatorConfig.interval > 0:
			logger.debug("Waiting for interval %d", self._generatorConfig.interval)
			self._event.wait(self._generatorConfig.interval)
			if self._stopped:
				return None
			return self.createEvent()
		self._event.wait()
		return None

	def cleanup(self) -> None:
		pass

	def fireEvent(self, event: Event | None = None, can_cancel: bool = False) -> None:
		logger.debug("Trying to fire event %s", event)
		if self._stopped:
			logger.debug("%s is stopped, not firing event.", self)
			return

		if not event:
			logger.info("No event to fire")
			return

		self._lastEventOccurence = time.time()

		logger.info("Firing event '%s'", event)
		logger.info("Event info:")
		for key, value in event.eventInfo.items():
			logger.info("     %s: %s", key, value)

		class FireEventThread(threading.Thread):
			def __init__(self, eventListener: EventListener, event: Event) -> None:
				threading.Thread.__init__(self, name=f"FireEventThread-{event.eventConfig.getId()}")
				self._eventListener = eventListener
				self._event = event

			def run(self) -> None:
				with opsicommon.logging.log_context({"instance": "event generator " + self._event.eventConfig.getId()}):
					if self._event.eventConfig.notificationDelay > 0:
						logger.debug(
							"Waiting %d seconds before notifying listener '%s' of event '%s'",
							self._event.eventConfig.notificationDelay,
							self._eventListener,
							self._event,
						)
						time.sleep(self._event.eventConfig.notificationDelay)
					try:
						logger.info("Calling processEvent on listener %s", self._eventListener)
						self._eventListener.processEvent(self._event)
					except Exception as err:
						logger.error(err, exc_info=True)

		logger.info("Starting FireEventThread for listeners: %s", self._eventListeners)
		keep_lock = False
		logger.trace("acquire lock (Basic), currently %s", self._opsiclientd.eventLock.locked())
		# timeout should be less than 15s as this is default opsi-admin call timeout
		if not self._opsiclientd.eventLock.acquire(timeout=5):
			raise ValueError("Could not get event handling lock due to another event currently running")
		try:
			for listener in self._eventListeners:
				# Check if all event listeners can handle the event
				# raises CannotCancelEventError if another event is already running
				listener.canProcessEvent(event, can_cancel=can_cancel)
			for listener in self._eventListeners:
				# Create a new thread for each event listener
				FireEventThread(listener, event).start()
			keep_lock = True
			logger.debug("keeping event processing lock (Basic)")
		finally:
			if not keep_lock:
				logger.trace("release lock (Basic)")
				self._opsiclientd.eventLock.release()

	def run(self) -> None:
		with opsicommon.logging.log_context({"instance": f"event generator {self._generatorConfig.getId()}"}):
			try:
				logger.info("Initializing event generator '%s'", self)
				self.initialize()

				if self._generatorConfig.activationDelay > 0:
					logger.debug(
						"Waiting %d seconds before activation of event generator '%s'", self._generatorConfig.activationDelay, self
					)
					time.sleep(self._generatorConfig.activationDelay)

				logger.info("Activating event generator '%s'", self)
				while not self._stopped and (
					(self._generatorConfig.maxRepetitions < 0) or (self._eventsOccured <= self._generatorConfig.maxRepetitions)
				):
					logger.info("Getting next event...")
					event = self.getNextEvent()
					self._eventsOccured += 1  # Count as occured, even if event is None!
					if event:
						logger.info("Got new event: %s (%d/%d)", event, self._eventsOccured, self._generatorConfig.maxRepetitions + 1)
						try:
							self.fireEvent(event)
						except CannotCancelEventError as cce_error:
							logger.warning("Event generator '%s' could not fire: %s", self, cce_error, exc_info=True)
					for _unused in range(10):
						if self._stopped:
							break
						time.sleep(1)
				if not self._stopped:
					logger.notice("Event generator '%s' now deactivated after %d event occurrences", self, self._eventsOccured)
			except Exception as err:
				if not self._stopped:
					logger.error("Failure in event generator '%s': %s", self, err, exc_info=True)
			try:
				self.cleanup()
			except Exception as err:
				if not self._stopped:
					logger.error("Failed to clean up: %s", err)

			logger.info("Event generator '%s' exiting ", self)

	def stop(self) -> None:
		self._stopped = True
		if self._event:
			self._event.set()


class Event:
	"""Basic event class"""

	def __init__(self, eventConfig: EventConfig, eventInfo: dict[str, str | list[str]] | None = None) -> None:
		self.eventConfig: EventConfig = eventConfig
		self.eventInfo: dict[str, str | list[str]] = eventInfo or {}

	def getActionProcessorCommand(self) -> str:
		actionProcessorCommand = self.eventConfig.actionProcessorCommand
		for key, value in self.eventInfo.items():
			actionProcessorCommand = actionProcessorCommand.replace("%" + "event." + str(key.lower()) + "%", str(value))

		return actionProcessorCommand


class EventListener:
	def __init__(self) -> None:
		logger.debug("EventListener initiated")

	def processEvent(self, event: Event) -> None:
		logger.warning("%s: processEvent() not implemented", self)

	def canProcessEvent(self, event: Event, can_cancel: bool = False) -> bool:
		logger.warning("%s: canProcessEvent() not implemented", self)
		raise NotImplementedError(f"{self}: canProcessEvent() not implemented")
