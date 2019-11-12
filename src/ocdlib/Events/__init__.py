# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2019 uib GmbH <info@uib.de>

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
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

from OPSI.Logger import Logger
from OPSI.Types import forceUnicode

from ocdlib.Config import Config

from .Configs import getEventConfigs
from .Factories import EventConfigFactory, EventGeneratorFactory
from .Panic import PanicEventConfig

EVENT_CONFIG_TYPE_PANIC = u'panic'

logger = Logger()
config = Config()


eventGenerators = {}
def createEventGenerators():
	global eventGenerators
	panicEventConfig = PanicEventConfig(
		EVENT_CONFIG_TYPE_PANIC,
		actionProcessorCommand=config.get('action_processor', 'command', raw=True)
	)
	eventGenerators[EVENT_CONFIG_TYPE_PANIC] = EventGeneratorFactory(panicEventConfig)

	for (eventConfigId, eventConfig) in getEventConfigs().items():
		mainEventConfigId = eventConfigId.split('{')[0]
		if (mainEventConfigId == eventConfigId):
			try:
				eventType = eventConfig['type']
				del eventConfig['type']
				ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
				eventGenerators[mainEventConfigId] = EventGeneratorFactory(ec)
				logger.notice("Event generator '%s' created" % mainEventConfigId)
			except Exception as e:
				logger.error(u"Failed to create event generator '%s': %s" % (mainEventConfigId, forceUnicode(e)))

	for (eventConfigId, eventConfig) in getEventConfigs().items():
		mainEventConfigId = eventConfigId.split('{')[0]
		eventType = eventConfig['type']
		del eventConfig['type']
		ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
		if mainEventConfigId not in eventGenerators:
			try:
				eventGenerators[mainEventConfigId] = EventGeneratorFactory(ec)
				logger.notice("Event generator '%s' created" % mainEventConfigId)
			except Exception as e:
				logger.error(u"Failed to create event generator '%s': %s" % (mainEventConfigId, forceUnicode(e)))

		try:
			eventGenerators[mainEventConfigId].addEventConfig(ec)
			logger.notice("Event config '%s' added to event generator '%s'" % (eventConfigId, mainEventConfigId))
		except Exception as e:
			logger.error(u"Failed to add event config '%s' to event generator '%s': %s" % (eventConfigId, mainEventConfigId, forceUnicode(e)))


def getEventGenerators(generatorClass=None):
	return [
		eventGenerator for eventGenerator in eventGenerators.values()
		if generatorClass is None or isinstance(eventGenerator, generatorClass)
	]


def reconfigureEventGenerators():
	eventConfigs = getEventConfigs()
	for eventGenerator in eventGenerators.values():
		eventGenerator.setEventConfigs([])

	for (eventConfigId, eventConfig) in eventConfigs.items():
		mainEventConfigId = eventConfigId.split('{')[0]

		try:
			eventGenerator = eventGenerators[mainEventConfigId]
		except KeyError:
			logger.info(u"Cannot reconfigure event generator '%s': not found" % mainEventConfigId)
			continue

		try:
			eventType = eventConfig['type']
			del eventConfig['type']
			ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
			eventGenerator.addEventConfig(ec)
			logger.notice("Event config '%s' added to event generator '%s'" % (eventConfigId, mainEventConfigId))
		except Exception as e:
			logger.error(u"Failed to reconfigure event generator '%s': %s" % (mainEventConfigId, forceUnicode(e)))
