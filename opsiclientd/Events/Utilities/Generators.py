# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
Functions to create, reconfigure and get event generators.
"""

from __future__ import absolute_import
import copy

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
	enabled_events = {}
	global _EVENT_GENERATORS # pylint: disable=global-statement
	panicEventConfig = PanicEventConfig(
		EVENT_CONFIG_TYPE_PANIC,
		actionProcessorCommand=config.get('action_processor', 'command', raw=True)
	)
	_EVENT_GENERATORS[EVENT_CONFIG_TYPE_PANIC] = EventGeneratorFactory(opsiclientd, panicEventConfig)
	enabled_events[EVENT_CONFIG_TYPE_PANIC] = True

	event_configs = getEventConfigs()
	# Create event generators for events without preconditions
	for (eventConfigId, eventConfig) in copy.deepcopy(event_configs).items():
		mainEventConfigId = eventConfigId.split('{')[0]
		if mainEventConfigId != eventConfigId:
			continue

		enabled_events[eventConfigId] = False
		if not eventConfig['active'] or eventConfig['type'] in config.disabledEventTypes:
			logger.info("Event %s of type %s is disabled", eventConfigId, eventConfig['type'])
			continue

		try:
			eventType = eventConfig['type']
			del eventConfig['type']
			ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
			_EVENT_GENERATORS[eventConfigId] = EventGeneratorFactory(opsiclientd, ec)
			logger.info("Event generator '%s' created", eventConfigId)
			enabled_events[eventConfigId] = True
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to create event generator '%s': %s", mainEventConfigId, err)

	# Create event generators for events with preconditions
	for (eventConfigId, eventConfig) in copy.deepcopy(event_configs).items():
		mainEventConfigId = eventConfigId.split('{')[0]
		if not mainEventConfigId in enabled_events:
			enabled_events[mainEventConfigId] = False
		if not eventConfigId in enabled_events:
			enabled_events[eventConfigId] = False

		if not eventConfig['active'] or eventConfig['type'] in config.disabledEventTypes:
			logger.info("Event %s of type %s is disabled", eventConfigId, eventConfig['type'])
			continue

		eventType = eventConfig['type']
		del eventConfig['type']
		ec = EventConfigFactory(eventType, eventConfigId, **eventConfig)
		if mainEventConfigId not in _EVENT_GENERATORS:
			try:
				_EVENT_GENERATORS[mainEventConfigId] = EventGeneratorFactory(opsiclientd, ec)
				logger.info("Event generator '%s' created", mainEventConfigId)
				enabled_events[mainEventConfigId] = True
			except Exception as err: # pylint: disable=broad-except
				logger.error("Failed to create event generator '%s': %s", mainEventConfigId, err)

		try:
			_EVENT_GENERATORS[mainEventConfigId].addEventConfig(ec)
			logger.info("Event config '%s' added to event generator '%s'", eventConfigId, mainEventConfigId)
			enabled_events[eventConfigId] = True
		except Exception as err: # pylint: disable=broad-except
			logger.error("Failed to add event config '%s' to event generator '%s': %s", eventConfigId, mainEventConfigId, err)

	logger.notice("Configured events: %s", ", ".join(sorted(list(enabled_events))))
	logger.notice("Enabled events: %s", ", ".join(sorted([evt_id for evt_id in enabled_events if enabled_events[evt_id]])))

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
