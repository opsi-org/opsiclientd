# -*- coding: utf-8 -*-

import pytest

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.Events.DaemonShutdown import DaemonShutdownEventConfig
from opsiclientd.Events.DaemonStartup import DaemonStartupEventConfig
from opsiclientd.Events.Panic import PanicEventConfig
from opsiclientd.Events.ProcessActionRequests import ProcessActionRequestsEventConfig
from opsiclientd.Events.SwOnDemand import SwOnDemandEventConfig
from opsiclientd.Events.SyncCompleted import SyncCompletedEventConfig
from opsiclientd.Events.Timer import TimerEventConfig


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
