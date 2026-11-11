# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
test_event_config
"""

import logging
from collections.abc import Generator

import pytest
from opsi.logging import DEBUG, INFO, LOG_DEBUG, LOG_TRACE, NOTICE, logger

from opsiclientd.Config import Config
from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.Events.DaemonShutdown import DaemonShutdownEventConfig
from opsiclientd.Events.DaemonStartup import DaemonStartupEventConfig
from opsiclientd.Events.Panic import PanicEventConfig
from opsiclientd.Events.ProcessActionRequests import ProcessActionRequestsEventConfig
from opsiclientd.Events.SwOnDemand import SwOnDemandEventConfig
from opsiclientd.Events.SyncCompleted import SyncCompletedEventConfig
from opsiclientd.Events.Timer import TimerEventConfig
from opsiclientd.Events.Utilities.Configs import getEventConfigs
from opsiclientd.Events.Utilities.Generators import reconfigureEventGenerators

from .utils import load_config_file


@pytest.fixture(
	params=[
		DaemonShutdownEventConfig,
		DaemonStartupEventConfig,
		EventConfig,
		PanicEventConfig,
		TimerEventConfig,
		ProcessActionRequestsEventConfig,
		SwOnDemandEventConfig,
		SyncCompletedEventConfig,
	]
)
def configClass(request: pytest.FixtureRequest) -> Generator[type[EventConfig]]:
	yield request.param


def testCreatingNewEventConfig(configClass: type[EventConfig]) -> None:
	configClass("testevent")


def testAttributesForWhiteAndBlackListExist(configClass: type[EventConfig]) -> None:
	config = configClass("testevent")
	assert hasattr(config, "excludeProductGroupIds")
	assert hasattr(config, "includeProductGroupIds")


def test_inheritance() -> None:
	load_config_file("tests/data/event_config/1.conf")

	configs = getEventConfigs()
	assert sorted(configs) == sorted(
		[
			"gui_startup",
			"gui_startup{cache_ready}",
			"gui_startup{installation_pending}",
			"gui_startup{user_logged_in}",
			"maintenance",
			"net_connection",
			"on_demand",
			"on_demand{user_logged_in}",
			"on_shutdown",
			"on_shutdown{installation_pending}",
			"opsiclientd_start",
			"opsiclientd_start{cache_ready}",
			"silent_install",
			"software_on_demand",
			"sync_completed",
			"sync_completed{cache_ready_user_logged_in}",
			"sync_completed{cache_ready}",
			"timer",
			"timer_silentinstall",
			"user_login",
		]
	)
	assert configs["on_demand"]["shutdownWarningTime"] == 3600
	assert configs["on_demand{user_logged_in}"]["shutdownWarningTime"] == 36000

	Config().set(section="event_default", option="shutdown_warning_time", value=12345)
	reconfigureEventGenerators()

	configs = getEventConfigs()
	assert configs["on_demand"]["shutdownWarningTime"] == 12345
	assert configs["on_demand{user_logged_in}"]["shutdownWarningTime"] == 36000

	assert configs["gui_startup"]["shutdownWarningTime"] == 12345
	assert configs["gui_startup{cache_ready}"]["shutdownWarningTime"] == 12345
	assert configs["gui_startup{installation_pending}"]["shutdownWarningTime"] == 12345


def test_get_event_configs_logs_config_once_on_first_load(monkeypatch: pytest.MonkeyPatch) -> None:
	load_config_file("tests/data/event_config/1.conf")
	monkeypatch.setattr("opsiclientd.Events.Utilities.Configs._last_event_configs", None)

	records: list[logging.LogRecord] = []

	class EventConfigLogHandler(logging.Handler):
		def emit(self, record: logging.LogRecord) -> None:
			records.append(record)

	handler = EventConfigLogHandler()
	previous_level = logger.level
	logger.addHandler(handler)
	logger.setLevel(LOG_DEBUG)
	try:
		configs = getEventConfigs()
		first_load = [r.getMessage() for r in records if r.levelno == INFO and "Event config '" in r.getMessage()]
		records.clear()
		getEventConfigs()
		second_load = [r.getMessage() for r in records if r.levelno == INFO and "Event config '" in r.getMessage()]
	finally:
		logger.removeHandler(handler)
		logger.setLevel(previous_level)

	assert len(first_load) == len(configs)
	assert all(" loaded:" in msg for msg in first_load)
	assert not second_load


def test_get_event_configs_logs_only_changes_at_notice() -> None:
	load_config_file("tests/data/event_config/1.conf")
	# Baseline load
	getEventConfigs()

	records: list[logging.LogRecord] = []

	class EventConfigLogHandler(logging.Handler):
		def emit(self, record: logging.LogRecord) -> None:
			records.append(record)

	handler = EventConfigLogHandler()
	previous_level = logger.level
	logger.addHandler(handler)
	logger.setLevel(LOG_TRACE)
	try:
		# Reload without modification: nothing changed
		getEventConfigs()
		assert not [r for r in records if r.levelno == INFO and "Event config '" in r.getMessage()]

		records.clear()
		Config().set(section="event_timer", option="interval", value=12345)
		getEventConfigs()
	finally:
		logger.removeHandler(handler)
		logger.setLevel(previous_level)

	infos = [r.getMessage() for r in records if r.levelno == INFO and "Event config '" in r.getMessage()]
	assert len(infos) == 1
	assert infos[0].startswith("Event config 'timer' changed:")
	assert "'interval': (" in infos[0]
	assert "12345" in infos[0]
	assert "actionMessage" not in infos[0]

	assert any(r.levelno <= DEBUG and "Event config 'timer' args:" in r.getMessage() for r in records)
