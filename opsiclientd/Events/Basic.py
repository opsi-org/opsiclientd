# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
Basic event building blocks.
"""

from __future__ import absolute_import

import threading
import time

import opsicommon.logging
from opsicommon.logging import logger
from OPSI.Types import forceList

from opsiclientd.State import State

__all__ = ['Event', 'EventGenerator', 'EventListener']

#logger = Logger()
state = State()


class EventGenerator(threading.Thread): # pylint: disable=too-many-instance-attributes
	def __init__(self, opsiclientd, generatorConfig):
		threading.Thread.__init__(self, daemon=True)
		self._opsiclientd = opsiclientd
		self._generatorConfig = generatorConfig
		self._eventConfigs = []
		self._eventListeners = []
		self._eventsOccured = 0
		self._threadId = None
		self._stopped = False
		self._event = None
		self._lastEventOccurence = None

	def __str__(self):
		return f'<{self.__class__.__name__} {self._generatorConfig.getId()}>'

	__repr__ = __str__

	def setEventConfigs(self, eventConfigs):
		self._eventConfigs = forceList(eventConfigs)

	def addEventConfig(self, eventConfig):
		self._eventConfigs.append(eventConfig)

	def _preconditionsFulfilled(self, preconditions): # pylint: disable=no-self-use
		for key, value in preconditions.items():
			if bool(value) != state.get(key):
				return False

		return True

	def addEventListener(self, eventListener):
		if not isinstance(eventListener, EventListener):
			raise TypeError("Failed to add event listener, got class %s, need class EventListener" % eventListener.__class__)

		if eventListener in self._eventListeners:
			return

		self._eventListeners.append(eventListener)

	def getEventConfig(self):
		logger.info("Testing preconditions of configs: %s", self._eventConfigs)
		actualConfig = {'preconditions': {}, 'config': None}
		for pec in self._eventConfigs:
			if self._preconditionsFulfilled(pec.preconditions):
				logger.info("Preconditions %s for event config '%s' fulfilled", pec.preconditions, pec.getId())
				if not actualConfig['config'] or (len(pec.preconditions.keys()) > len(actualConfig['preconditions'].keys())):
					actualConfig = {'preconditions': pec.preconditions, 'config': pec}
			else:
				logger.info("Preconditions %s for event config '%s' not fulfilled", pec.preconditions, pec.getId())

		return actualConfig['config']

	def createAndFireEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		self.fireEvent(self.createEvent(eventInfo))

	def createEvent(self, eventInfo={}): # pylint: disable=dangerous-default-value
		logger.debug("Creating event config from info: %s", eventInfo)
		eventConfig = self.getEventConfig()
		logger.debug("Event config: %s", eventConfig)
		if not eventConfig:
			return None

		return Event(eventConfig=eventConfig, eventInfo=eventInfo)

	def initialize(self):
		pass

	def getNextEvent(self):
		self._event = threading.Event()
		self._event.wait()

	def cleanup(self):
		pass

	def fireEvent(self, event=None):
		logger.debug("Trying to fire event %s", event)
		if self._stopped:
			logger.debug('%s is stopped, not firing event.', self)
			return

		if not event:
			logger.info("No event to fire")
			return

		self._lastEventOccurence = time.time()

		logger.info("Firing event '%s'", event)
		logger.info("Event info:")
		for (key, value) in event.eventInfo.items():
			logger.info("     %s: %s", key, value)

		class FireEventThread(threading.Thread):
			def __init__(self, eventListener, event):
				threading.Thread.__init__(self)
				self._eventListener = eventListener
				self._event = event

			def run(self):
				with opsicommon.logging.log_context({'instance' : 'event generator ' + self._event.eventConfig.getId()}):
					if self._event.eventConfig.notificationDelay > 0:
						logger.debug("Waiting %d seconds before notifying listener '%s' of event '%s'",
							self._event.eventConfig.notificationDelay, self._eventListener, self._event
						)
						time.sleep(self._event.eventConfig.notificationDelay)
					try:
						logger.info("Calling processEvent on listener %s", self._eventListener)
						self._eventListener.processEvent(self._event)
					except Exception as err: # pylint: disable=broad-except
						logger.error(err, exc_info=True)

		logger.info("Starting FireEventThread for listeners: %s", self._eventListeners)
		for listener in self._eventListeners:
			# Create a new thread for each event listener
			FireEventThread(listener, event).start()

	def run(self):
		with opsicommon.logging.log_context({'instance' : f'event generator {self._generatorConfig.getId()}'}):
			try:
				logger.info("Initializing event generator '%s'", self)
				self.initialize()

				if self._generatorConfig.activationDelay > 0:
					logger.debug("Waiting %d seconds before activation of event generator '%s'",
						self._generatorConfig.activationDelay, self
					)
					time.sleep(self._generatorConfig.activationDelay)

				logger.info("Activating event generator '%s'", self)
				while not self._stopped and (
					(self._generatorConfig.maxRepetitions < 0) or
					(self._eventsOccured <= self._generatorConfig.maxRepetitions)
				):
					logger.info("Getting next event...")
					event = self.getNextEvent() # pylint: disable=assignment-from-none,assignment-from-no-return
					self._eventsOccured += 1 # Count as occured, even if event is None!
					if event:
						logger.info("Got new event: %s (%d/%d)", event, self._eventsOccured, self._generatorConfig.maxRepetitions + 1)
						self.fireEvent(event)
					for _unused in range(10):
						if self._stopped:
							break
						time.sleep(1)
				if not self._stopped:
					logger.notice("Event generator '%s' now deactivated after %d event occurrences", self, self._eventsOccured)
			except Exception as err: # pylint: disable=broad-except
				if not self._stopped:
					logger.error("Failure in event generator '%s': %s", self, err, exc_info=True)
			try:
				self.cleanup()
			except Exception as err: # pylint: disable=broad-except
				if not self._stopped:
					logger.error("Failed to clean up: %s", err)

			logger.info("Event generator '%s' exiting ", self)

	def stop(self):
		self._stopped = True
		if self._event:
			self._event.set()


class Event: # pylint: disable=too-few-public-methods
	""" Basic event class """
	def __init__(self, eventConfig, eventInfo={}): # pylint: disable=dangerous-default-value
		self.eventConfig = eventConfig
		self.eventInfo = eventInfo

	def getActionProcessorCommand(self):
		actionProcessorCommand = self.eventConfig.actionProcessorCommand
		for (key, value) in self.eventInfo.items():
			actionProcessorCommand = actionProcessorCommand.replace('%' + 'event.' + str(key.lower()) + '%', str(value))

		return actionProcessorCommand


class EventListener: # pylint: disable=too-few-public-methods
	def __init__(self):
		logger.debug("EventListener initiated")

	def processEvent(self, event): # pylint: disable=unused-argument
		logger.warning("%s: processEvent() not implemented", self)
