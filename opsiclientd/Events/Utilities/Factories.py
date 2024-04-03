# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Factories for creation of event configs or generators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opsiclientd.Events.Basic import EventConfig, EventGenerator
from opsiclientd.Events.Custom import CustomEventConfig, CustomEventGenerator
from opsiclientd.Events.DaemonShutdown import (
	DaemonShutdownEventConfig,
	DaemonShutdownEventGenerator,
)
from opsiclientd.Events.DaemonStartup import (
	DaemonStartupEventConfig,
	DaemonStartupEventGenerator,
)
from opsiclientd.Events.GUIStartup import (
	GUIStartupEventConfig,
	GUIStartupEventGenerator,
)
from opsiclientd.Events.Panic import PanicEventConfig, PanicEventGenerator
from opsiclientd.Events.ProcessActionRequests import (
	ProcessActionRequestsEventConfig,
	ProcessActionRequestsEventGenerator,
)
from opsiclientd.Events.SwOnDemand import (
	SwOnDemandEventConfig,
	SwOnDemandEventGenerator,
)
from opsiclientd.Events.SyncCompleted import (
	SyncCompletedEventConfig,
	SyncCompletedEventGenerator,
)
from opsiclientd.Events.Timer import TimerEventConfig, TimerEventGenerator
from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

if RUNNING_ON_WINDOWS:
	from opsiclientd.Events.Windows.SystemShutdown import (
		SystemShutdownEventConfig,
		SystemShutdownEventGenerator,
	)
	from opsiclientd.Events.Windows.UserLogin import (
		UserLoginEventConfig,
		UserLoginEventGenerator,
	)

if TYPE_CHECKING:
	from opsiclientd.Opsiclientd import Opsiclientd


__all__ = ["EventConfigFactory", "EventGeneratorFactory"]


def EventConfigFactory(eventType: str, eventId: str, **kwargs: Any) -> EventConfig:
	"""
	Get an event config for the given type.

	Additional keyword arguments will be passed to the created config
	for initialisation.

	:param eventType: the type of the event
	:type eventType: str
	:param eventId: ID for the config
	:type eventId: str
	:rtype: EventConfig
	"""
	if eventType == "panic":
		return PanicEventConfig(eventId, **kwargs)
	if eventType == "daemon startup":
		return DaemonStartupEventConfig(eventId, **kwargs)
	if eventType == "daemon shutdown":
		return DaemonShutdownEventConfig(eventId, **kwargs)
	if eventType == "timer":
		return TimerEventConfig(eventId, **kwargs)
	if eventType == "sync completed":
		return SyncCompletedEventConfig(eventId, **kwargs)
	if eventType == "process action requests":
		return ProcessActionRequestsEventConfig(eventId, **kwargs)
	if eventType == "custom":
		return CustomEventConfig(eventId, **kwargs)
	if eventType == "sw on demand":
		return SwOnDemandEventConfig(eventId, **kwargs)
	if eventType == "gui startup":
		return GUIStartupEventConfig(eventId, **kwargs)

	if RUNNING_ON_WINDOWS:
		if eventType == "user login":
			return UserLoginEventConfig(eventId, **kwargs)
		if eventType == "system shutdown":
			return SystemShutdownEventConfig(eventId, **kwargs)

	raise TypeError(f"Unknown event config type '{eventType}'")


def EventGeneratorFactory(opsiclientd: Opsiclientd, eventConfig: EventConfig) -> EventGenerator:
	"""
	Get an event generator matching the given config type.

	:type eventConfig: EventConfig
	:rtype: EventGenerator
	"""
	if isinstance(eventConfig, PanicEventConfig):
		return PanicEventGenerator(opsiclientd, eventConfig)
	if isinstance(eventConfig, DaemonStartupEventConfig):
		return DaemonStartupEventGenerator(opsiclientd, eventConfig)
	if isinstance(eventConfig, DaemonShutdownEventConfig):
		return DaemonShutdownEventGenerator(opsiclientd, eventConfig)
	if isinstance(eventConfig, TimerEventConfig):
		return TimerEventGenerator(opsiclientd, eventConfig)
	if isinstance(eventConfig, SyncCompletedEventConfig):
		return SyncCompletedEventGenerator(opsiclientd, eventConfig)
	if isinstance(eventConfig, ProcessActionRequestsEventConfig):
		return ProcessActionRequestsEventGenerator(opsiclientd, eventConfig)
	if isinstance(eventConfig, CustomEventConfig):
		return CustomEventGenerator(opsiclientd, eventConfig)
	if isinstance(eventConfig, SwOnDemandEventConfig):
		return SwOnDemandEventGenerator(opsiclientd, eventConfig)
	if isinstance(eventConfig, GUIStartupEventConfig):
		return GUIStartupEventGenerator(opsiclientd, eventConfig)

	if RUNNING_ON_WINDOWS:
		if isinstance(eventConfig, UserLoginEventConfig):
			return UserLoginEventGenerator(opsiclientd, eventConfig)
		if isinstance(eventConfig, SystemShutdownEventConfig):
			return SystemShutdownEventGenerator(opsiclientd, eventConfig)

	raise TypeError(f"Unhandled event config '{eventConfig}'")
