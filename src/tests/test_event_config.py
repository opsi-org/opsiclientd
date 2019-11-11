# -*- coding: utf-8 -*-

import pytest

from ocdlib.EventConfiguration import EventConfig
from ocdlib.Events import ProcessActionRequestsEventConfig
from ocdlib.Events.Panic import PanicEventConfig
from ocdlib.Events.DaemonShutdown import DaemonShutdownEventConfig
from ocdlib.Events.DaemonStartup import DaemonStartupEventConfig
from ocdlib.Events.SwOnDemand import SwOnDemandEventConfig
from ocdlib.Events.SyncCompleted import SyncCompletedEventConfig
from ocdlib.Events.Timer import TimerEventConfig


@pytest.fixture(params=[
    DaemonShutdownEventConfig, DaemonStartupEventConfig, EventConfig,
    PanicEventConfig, TimerEventConfig, ProcessActionRequestsEventConfig,
    SwOnDemandEventConfig, SyncCompletedEventConfig
])
def configClass(request):
    yield request.param


def testCreatingNewEventConfig(configClass):
    configClass("testevent")


def testAttributesForWhiteAndBlackListExist(configClass):
    config = configClass("testevent")

    assert hasattr(config, 'excludeProductGroupIds')
    assert hasattr(config, 'includeProductGroupIds')
