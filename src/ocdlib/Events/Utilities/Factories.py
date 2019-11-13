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

from ocdlib.SystemCheck import RUNNING_ON_WINDOWS

from ..Custom import CustomEventConfig, CustomEventGenerator
from ..DaemonShutdown import (
	DaemonShutdownEventConfig, DaemonShutdownEventGenerator)
from ..DaemonStartup import (
	DaemonStartupEventConfig, DaemonStartupEventGenerator)
from ..Panic import PanicEventConfig, PanicEventGenerator
from ..ProcessActionRequests import (
	ProcessActionRequestsEventConfig, ProcessActionRequestsEventGenerator)
from ..SwOnDemand import SwOnDemandEventConfig, SwOnDemandEventGenerator
from ..SyncCompleted import (
	SyncCompletedEventConfig, SyncCompletedEventGenerator)
from ..Timer import TimerEventConfig, TimerEventGenerator

if RUNNING_ON_WINDOWS:
	from ..Windows.GUIStartup import (
		GUIStartupEventConfig, GUIStartupEventGenerator)
	from ..Windows.SystemShutdown import (
		SystemShutdownEventConfig, SystemShutdownEventGenerator)
	from ..Windows.UserLogin import (
		UserLoginEventConfig, UserLoginEventGenerator)

__all__ = ['EventConfigFactory', 'EventGeneratorFactory']


def EventConfigFactory(eventType, eventId, **kwargs):
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
	if eventType == u'panic':
		return PanicEventConfig(eventId, **kwargs)
	elif eventType == u'daemon startup':
		return DaemonStartupEventConfig(eventId, **kwargs)
	elif eventType == u'daemon shutdown':
		return DaemonShutdownEventConfig(eventId, **kwargs)
	elif eventType == u'timer':
		return TimerEventConfig(eventId, **kwargs)
	elif eventType == u'sync completed':
		return SyncCompletedEventConfig(eventId, **kwargs)
	elif eventType == u'process action requests':
		return ProcessActionRequestsEventConfig(eventId, **kwargs)
	elif eventType == u'custom':
		return CustomEventConfig(eventId, **kwargs)
	elif eventType == u'sw on demand':
		return SwOnDemandEventConfig(eventId, **kwargs)

	if RUNNING_ON_WINDOWS:
		if eventType == u'gui startup':
			return GUIStartupEventConfig(eventId, **kwargs)
		elif eventType == u'user login':
			return UserLoginEventConfig(eventId, **kwargs)
		elif eventType == u'system shutdown':
			return SystemShutdownEventConfig(eventId, **kwargs)

	raise TypeError(u"Unknown event config type '%s'" % eventType)


def EventGeneratorFactory(eventConfig):
	"""
	Get an event generator matching the given config type.

	:type eventConfig: EventConfig
	:rtype: EventGenerator
	"""
	if isinstance(eventConfig, PanicEventConfig):
		return PanicEventGenerator(eventConfig)
	elif isinstance(eventConfig, DaemonStartupEventConfig):
		return DaemonStartupEventGenerator(eventConfig)
	elif isinstance(eventConfig, DaemonShutdownEventConfig):
		return DaemonShutdownEventGenerator(eventConfig)
	elif isinstance(eventConfig, TimerEventConfig):
		return TimerEventGenerator(eventConfig)
	elif isinstance(eventConfig, SyncCompletedEventConfig):
		return SyncCompletedEventGenerator(eventConfig)
	elif isinstance(eventConfig, ProcessActionRequestsEventConfig):
		return ProcessActionRequestsEventGenerator(eventConfig)
	elif isinstance(eventConfig, CustomEventConfig):
		return CustomEventGenerator(eventConfig)
	elif isinstance(eventConfig, SwOnDemandEventConfig):
		return SwOnDemandEventGenerator(eventConfig)

	if RUNNING_ON_WINDOWS:
		if isinstance(eventConfig, UserLoginEventConfig):
			return UserLoginEventGenerator(eventConfig)
		elif isinstance(eventConfig, SystemShutdownEventConfig):
			return SystemShutdownEventGenerator(eventConfig)
		elif isinstance(eventConfig, GUIStartupEventConfig):
			return GUIStartupEventGenerator(eventConfig)

	raise TypeError(u"Unhandled event config '%s'" % eventConfig)
