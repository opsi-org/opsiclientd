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
Factories for creation of event configs or generators.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

from opsiclientd.SystemCheck import RUNNING_ON_WINDOWS

from opsiclientd.Events.Custom import CustomEventConfig, CustomEventGenerator
from opsiclientd.Events.DaemonShutdown import (
	DaemonShutdownEventConfig, DaemonShutdownEventGenerator
)
from opsiclientd.Events.DaemonStartup import (
	DaemonStartupEventConfig, DaemonStartupEventGenerator
)
from opsiclientd.Events.Panic import PanicEventConfig, PanicEventGenerator
from opsiclientd.Events.ProcessActionRequests import (
	ProcessActionRequestsEventConfig, ProcessActionRequestsEventGenerator
)
from opsiclientd.Events.SwOnDemand import SwOnDemandEventConfig, SwOnDemandEventGenerator
from opsiclientd.Events.SyncCompleted import (
	SyncCompletedEventConfig, SyncCompletedEventGenerator
)
from opsiclientd.Events.Timer import TimerEventConfig, TimerEventGenerator

if RUNNING_ON_WINDOWS:
	from opsiclientd.Events.Windows.GUIStartup import (
		GUIStartupEventConfig, GUIStartupEventGenerator
	)
	from opsiclientd.Events.Windows.SystemShutdown import (
		SystemShutdownEventConfig, SystemShutdownEventGenerator
	)
	from opsiclientd.Events.Windows.UserLogin import (
		UserLoginEventConfig, UserLoginEventGenerator
	)

__all__ = ['EventConfigFactory', 'EventGeneratorFactory']


def EventConfigFactory(eventType, eventId, **kwargs): # pylint: disable=invalid-name,too-many-return-statements
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
	if eventType == 'panic':
		return PanicEventConfig(eventId, **kwargs)
	if eventType == 'daemon startup':
		return DaemonStartupEventConfig(eventId, **kwargs)
	if eventType == 'daemon shutdown':
		return DaemonShutdownEventConfig(eventId, **kwargs)
	if eventType == 'timer':
		return TimerEventConfig(eventId, **kwargs)
	if eventType == 'sync completed':
		return SyncCompletedEventConfig(eventId, **kwargs)
	if eventType == 'process action requests':
		return ProcessActionRequestsEventConfig(eventId, **kwargs)
	if eventType == 'custom':
		return CustomEventConfig(eventId, **kwargs)
	if eventType == 'sw on demand':
		return SwOnDemandEventConfig(eventId, **kwargs)

	if RUNNING_ON_WINDOWS:
		if eventType == 'gui startup':
			return GUIStartupEventConfig(eventId, **kwargs)
		if eventType == 'user login':
			return UserLoginEventConfig(eventId, **kwargs)
		if eventType == 'system shutdown':
			return SystemShutdownEventConfig(eventId, **kwargs)

	raise TypeError(f"Unknown event config type '{eventType}'")


def EventGeneratorFactory(opsiclientd, eventConfig): # pylint: disable=invalid-name,too-many-return-statements
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

	if RUNNING_ON_WINDOWS:
		if isinstance(eventConfig, UserLoginEventConfig):
			return UserLoginEventGenerator(opsiclientd, eventConfig)
		if isinstance(eventConfig, SystemShutdownEventConfig):
			return SystemShutdownEventGenerator(opsiclientd, eventConfig)
		if isinstance(eventConfig, GUIStartupEventConfig):
			return GUIStartupEventGenerator(opsiclientd, eventConfig)

	raise TypeError(f"Unhandled event config '{eventConfig}'")
