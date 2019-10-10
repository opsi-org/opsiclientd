# -*- coding: utf-8 -*-

import pytest

from ocdlib.EventConfiguration import EventConfig
from ocdlib.Events import (DaemonShutdownEventConfig, DaemonStartupEventConfig,
    PanicEventConfig, TimerEventConfig, ProcessActionRequestsEventConfig,
    SwOnDemandEventConfig, SyncCompletedEventConfig)


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
