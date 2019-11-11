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
Panic events are used to react to problems.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:author: Erol Ueluekmen <e.ueluekmen@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

from .Basic import Event, EventGenerator
from ocdlib.EventConfiguration import EventConfig

__all__ = [
    'EVENT_CONFIG_TYPE_PANIC', 'PanicEvent', 'PanicEventConfig',
    'PanicEventGenerator'
]

EVENT_CONFIG_TYPE_PANIC = u'panic'


class PanicEventConfig(EventConfig):
    def setConfig(self, conf):
        EventConfig.setConfig(self, conf)
        self.maxRepetitions = -1
        self.actionMessage = 'Panic event'
        self.activationDelay = 0
        self.notificationDelay = 0
        self.actionWarningTime = 0
        self.actionUserCancelable = False
        self.blockLogin = False
        self.logoffCurrentUser = False
        self.lockWorkstation = False
        self.getConfigFromService = False
        self.updateConfigFile = False
        self.writeLogToService = False
        self.updateActionProcessor = False
        self.eventNotifierCommand = None
        self.actionNotifierCommand = None
        self.shutdownNotifierCommand = None
        self.actionProcessorDesktop = 'winlogon'


class PanicEventGenerator(EventGenerator):

    def createEvent(self, eventInfo={}):
        eventConfig = self.getEventConfig()
        if not eventConfig:
            return None

        return PanicEvent(eventConfig=eventConfig, eventInfo=eventInfo)


class PanicEvent(Event):
    pass
