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
Events and their configuration.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

import thread
import threading
import time

from OPSI.Logger import Logger
from OPSI.Types import forceList, forceUnicode

from ocdlib.Config import getLogFormat
from ocdlib.State import State

__all__ = ['Event', 'EventGenerator', 'EventListener']

logger = Logger()
state = State()


class EventGenerator(threading.Thread):
	def __init__(self, generatorConfig):
		threading.Thread.__init__(self)
		self._eventConfigs = []
		self._generatorConfig = generatorConfig
		self._eventListeners = []
		self._eventsOccured = 0
		self._threadId = None
		self._stopped = False
		self._event = None
		self._lastEventOccurence = None
		logger.setLogFormat(getLogFormat(u'event generator ' + self._generatorConfig.getId()), object=self)

	def __unicode__(self):
		return u'<%s %s>' % (self.__class__.__name__, self._generatorConfig.getId())

	__repr__ = __unicode__

	def setEventConfigs(self, eventConfigs):
		self._eventConfigs = forceList(eventConfigs)

	def addEventConfig(self, eventConfig):
		self._eventConfigs.append(eventConfig)

	def _preconditionsFulfilled(self, preconditions):
		for (k, v) in preconditions.items():
			if (bool(v) != state.get(k)):
				return False
		return True

	def addEventListener(self, eventListener):
		if not isinstance(eventListener, EventListener):
			raise TypeError(u"Failed to add event listener, got class %s, need class EventListener" % eventListener.__class__)

		for l in self._eventListeners:
			if (l == eventListener):
				return

		self._eventListeners.append(eventListener)

	def getEventConfig(self):
		logger.info(u"Testing preconditions of configs: %s" % self._eventConfigs)
		actualConfig = {'preconditions': {}, 'config': None}
		for pec in self._eventConfigs:
			if self._preconditionsFulfilled(pec.preconditions):
				logger.info(u"Preconditions %s for event config '%s' fulfilled" % (pec.preconditions, pec.getId()))
				if not actualConfig['config'] or (len(pec.preconditions.keys()) > len(actualConfig['preconditions'].keys())):
					actualConfig = {'preconditions': pec.preconditions, 'config': pec}
			else:
				logger.info(u"Preconditions %s for event config '%s' not fulfilled" % (pec.preconditions, pec.getId()))

		return actualConfig['config']

	def createAndFireEvent(self, eventInfo={}):
		self.fireEvent(self.createEvent(eventInfo))

	def createEvent(self, eventInfo={}):
		logger.debug("Creating event config from info: {0}".format(eventInfo))
		eventConfig = self.getEventConfig()
		logger.debug("Event config: {0}".format(eventConfig))
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
		logger.debug("Trying to fire event {0}".format(event))
		if self._stopped:
			logger.debug('{0} is stopped, not firing event.'.format(self))
			return

		if not event:
			logger.info(u"No event to fire")
			return

		self._lastEventOccurence = time.time()

		logger.info(u"Firing event '%s'" % event)
		logger.info(u"Event info:")
		for (key, value) in event.eventInfo.items():
			logger.info(u"     %s: %s" % (key, value))

		class FireEventThread(threading.Thread):
			def __init__(self, eventListener, event):
				threading.Thread.__init__(self)
				self._eventListener = eventListener
				self._event = event
				logger.setLogFormat(getLogFormat(u'event generator ' + self._event.eventConfig.getId()), object=self)

			def run(self):
				if (self._event.eventConfig.notificationDelay > 0):
					logger.debug(u"Waiting %d seconds before notifying listener '%s' of event '%s'" \
						% (self._event.eventConfig.notificationDelay, self._eventListener, self._event))
					time.sleep(self._event.eventConfig.notificationDelay)
				try:
					logger.info(u"Calling processEvent on listener %s" % self._eventListener)
					self._eventListener.processEvent(self._event)
				except Exception, e:
					logger.logException(e)

		logger.info(u"Starting FireEventThread for listeners: %s" % self._eventListeners)
		for l in self._eventListeners:
			# Create a new thread for each event listener
			FireEventThread(l, event).start()

	def run(self):
		self._threadId = thread.get_ident()
		try:
			logger.info(u"Initializing event generator '%s'" % self)
			self.initialize()

			if (self._generatorConfig.activationDelay > 0):
				logger.debug(u"Waiting %d seconds before activation of event generator '%s'" % \
					(self._generatorConfig.activationDelay, self))
				time.sleep(self._generatorConfig.activationDelay)

			logger.info(u"Activating event generator '%s'" % self)
			while not self._stopped and ( (self._generatorConfig.maxRepetitions < 0) or (self._eventsOccured <= self._generatorConfig.maxRepetitions) ):
				logger.info(u"Getting next event...")
				event = self.getNextEvent()
				self._eventsOccured += 1
				self.fireEvent(event)
			logger.info(u"Event generator '%s' now deactivated after %d event occurrences" % (self, self._eventsOccured))
		except Exception as e:
			logger.error(u"Failure in event generator '%s': %s" % (self, forceUnicode(e)))
			logger.logException(e)

		try:
			self.cleanup()
		except Exception, e:
			logger.error(u"Failed to clean up: %s" % forceUnicode(e))

		logger.info(u"Event generator '%s' exiting " % self)

	def stop(self):
		self._stopped = True
		if self._event:
			self._event.set()


class Event(object):
	def __init__(self, eventConfig, eventInfo={}):
		self.eventConfig = eventConfig
		self.eventInfo = eventInfo
		logger.setLogFormat(getLogFormat(u'event generator ' + self.eventConfig.getId()), object=self)

	def getActionProcessorCommand(self):
		actionProcessorCommand = self.eventConfig.actionProcessorCommand
		for (key, value) in self.eventInfo.items():
			actionProcessorCommand = actionProcessorCommand.replace(u'%' + u'event.' + unicode(key.lower()) + u'%', unicode(value))

		return actionProcessorCommand


class EventListener(object):
	def __init__(self):
		logger.debug(u"EventListener initiated")

	def processEvent(self, event):
		logger.warning(u"%s: processEvent() not implemented" % self)
