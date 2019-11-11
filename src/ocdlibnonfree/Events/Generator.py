# -*- coding: utf-8 -*-

# ocdlibnonfree is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org

# Copyright (C) 2015-2019 uib GmbH
# http://www.uib.de/
# All rights reserved.
"""
ocdlibnonfree.Events

:copyright:	uib GmbH <info@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
"""

from ocdlib.Events.Basic import Event, EventGenerator


class CustomEventGenerator(EventGenerator):
    def createEvent(self, eventInfo={}):
        eventConfig = self.getEventConfig()
        if not eventConfig:
            return None

        return CustomEvent(eventConfig=eventConfig, eventInfo=eventInfo)

    def getNextEvent(self):
        self._event = threading.Event()
        if self._generatorConfig.interval > 0:
            self._event.wait(self._generatorConfig.interval)
            return self.createEvent()
        else:
            self._event.wait()


class CustomEvent(Event):
    pass
