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
Functions to create, reconfigure and get event generators.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

from OPSI.Logger import Logger
from OPSI.Types import forceUnicode

from opsiclientd.Config import Config

from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.Events.Utilities.Factories import EventConfigFactory, EventGeneratorFactory
from opsiclientd.Events.Panic import PanicEventConfig

__all__ = [
	'createEventGenerators', 'getEventGenerator', 'getEventGenerators',
	'reconfigureEventGenerators',
]

EVENT_CONFIG_TYPE_PANIC = u'panic'
_EVENT_GENERATORS = {}

logger = Logger()
config = Config()


def createEventGenerators(opsiclientd):
	global _EVENT_GENERATORS # pylint: disable=global-statement
	panicEventConfig = PanicEventConfig(
		EVENT_CONFIG_TYPE_PANIC,
		actionProcessorCommand=config.get('action_processor', 'command', raw=True)
	)
	_EVENT_GENERATORS[EVENT_CONFIG_TYPE_PANIC] = EventGeneratorFactory(opsiclientd, panicEventConfig)

	for (eventConfigId, eventConfig) in getEventConfigs().items():
		if eventConfig['type'] in config.disabledEventTypes:
			logger.notice("Event %s of type %s is disabled", eventConfigId, eventConfig['type'])
			continue

		mainEventConfigId = eventConfigId.split('{')[0]
		if mainEventConfigId == eventConfigId:
			try:
				eventType = eventConfig['type']
				del eventConfig['type']
				ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
				_EVENT_GENERATORS[mainEventConfigId] = EventGeneratorFactory(opsiclientd, ec)
				logger.notice("Event generator '%s' created", mainEventConfigId)
			except Exception as err: # pylint: disable=broad-except
				logger.error("Failed to create event generator '%s': %s", mainEventConfigId, err)

	for (eventConfigId, eventConfig) in getEventConfigs().items():
		if eventConfig['type'] in config.disabledEventTypes:
			logger.notice("Event %s of type %s is disabled", eventConfigId, eventConfig['type'])
			continue

		mainEventConfigId = eventConfigId.split('{')[0]
		eventType = eventConfig['type']
		del eventConfig['type']
		ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
		if mainEventConfigId not in _EVENT_GENERATORS:
			try:
				_EVENT_GENERATORS[mainEventConfigId] = EventGeneratorFactory(opsiclientd, ec)
				logger.notice("Event generator '%s' created", mainEventConfigId)
			except Exception as err: # pylint: disable=broad-except
				logger.error("Failed to create event generator '%s': %s", mainEventConfigId, err)

		try:
			_EVENT_GENERATORS[mainEventConfigId].addEventConfig(ec)
			logger.notice("Event config '%s' added to event generator '%s'", eventConfigId, mainEventConfigId)
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to add event config '%s' to event generator '%s': %s", eventConfigId, mainEventConfigId, err)

def getEventGenerators(generatorClass=None):
	return [
		eventGenerator for eventGenerator in _EVENT_GENERATORS.values()
		if generatorClass is None or isinstance(eventGenerator, generatorClass)
	]

def getEventGenerator(name):
	"""
	Get the event generator for the event with the given name.

	:type name: str
	:rtype: EventGenerator
	:raises: ValueError if no matching event found.
	"""
	name = forceUnicode(name)
	try:
		return _EVENT_GENERATORS[name]
	except KeyError as err:
		raise ValueError(f"Event '{name}' not in list of known events: {', '.join(_EVENT_GENERATORS.keys())}") from err

def reconfigureEventGenerators():
	eventConfigs = getEventConfigs()
	for eventGenerator in _EVENT_GENERATORS.values():
		eventGenerator.setEventConfigs([])

	for (eventConfigId, eventConfig) in eventConfigs.items():
		mainEventConfigId = eventConfigId.split('{')[0]

		try:
			eventGenerator = _EVENT_GENERATORS[mainEventConfigId]
		except KeyError:
			logger.info("Cannot reconfigure event generator '%s': not found", mainEventConfigId)
			continue

		try:
			eventType = eventConfig['type']
			del eventConfig['type']
			ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
			eventGenerator.addEventConfig(ec)
			logger.notice("Event config '%s' added to event generator '%s'", eventConfigId, mainEventConfigId)
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to reconfigure event generator '%s': %s", mainEventConfigId, err)
