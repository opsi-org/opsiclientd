# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest
from opsicommon.logging import LOG_INFO, use_logging_config

from opsiclientd.Config import Config
from opsiclientd.Opsiclientd import Opsiclientd, state
from opsiclientd.webserver.rpc.control import get_control_interface

from .utils import default_config  # noqa

config = Config()


class FakeOpsiclientd(Opsiclientd):
	def showPopup(
		self,
		message: str,
		notifier_id: Literal["popup", "motd"] = "popup",
		mode: str = "prepend",
		addTimestamp: bool = True,
		displaySeconds: int = 0,
		link_handling: str = "no",
		sessions: list[int] | None = None,
		desktops: list[str] | None = None,
	) -> None:
		pass


@pytest.mark.parametrize(
	"user_logged_in, motd_enabled",
	(
		(False, True),
		(True, True),
		(True, False),
		(False, False)
	),
)
def test_motd_update_without_valid_until(default_config: Config, tmp_path: Path, user_logged_in: bool, motd_enabled: bool) -> None:  # noqa
	default_config.set("global", "message_of_the_day_enabled", motd_enabled)
	def getActiveSessionInformation() -> list[dict[str, str | int]]:
		if not user_logged_in:
			return []
		return [{"SessionId": 1, "UserName": "testuser"}, {"SessionId": 2, "UserName": "testuser2"}]

	ocd = FakeOpsiclientd()
	controlServer = get_control_interface(ocd)
	state._stateFile = str(tmp_path / "state_file.json")

	with use_logging_config(stderr_level=LOG_INFO):
		with patch("opsiclientd.Opsiclientd.System.getActiveSessionInformation", getActiveSessionInformation):
			first = controlServer.messageOfTheDayUpdated(
				user_message="Test message user",
				user_message_valid_until=0,
				device_message="Test message device",
				device_message_valid_until=None,  # type: ignore[arg-type]
			)
			second = controlServer.messageOfTheDayUpdated(user_message="Test message user", device_message="Test message device")

			if motd_enabled:
				# First should be shown
				if user_logged_in:
					assert first == ["user"]
				else:
					assert first == ["device"]
				# Second should not be shown (same hash)
				assert second == []
			else:
				assert first == []
				assert second == []


@pytest.mark.parametrize(
	"user_logged_in",
	(False, True),
)
def test_motd_update_valid_until(default_config: Config, tmp_path: Path, user_logged_in: bool) -> None:  # noqa
	default_config.set("global", "message_of_the_day_enabled", True)
	def getActiveSessionInformation() -> list[dict[str, str | int]]:
		if not user_logged_in:
			return []
		return [{"SessionId": 1, "UserName": "testuser"}, {"SessionId": 2, "UserName": "testuser2"}]

	ocd = FakeOpsiclientd()
	controlServer = get_control_interface(ocd)
	state._stateFile = str(tmp_path / "state_file.json")

	with patch("opsiclientd.Opsiclientd.System.getActiveSessionInformation", getActiveSessionInformation):
		valid_until = int((datetime.now(tz=timezone.utc) - timedelta(days=1)).timestamp())
		first = controlServer.messageOfTheDayUpdated(
			user_message="usermsg1",
			device_message="devicemsg1",
			user_message_valid_until=valid_until,
			device_message_valid_until=valid_until,
		)
		valid_until = int((datetime.now(tz=timezone.utc) + timedelta(days=1)).timestamp())
		second = controlServer.messageOfTheDayUpdated(
			user_message="usermsg2",
			device_message="devicemsg2",
			user_message_valid_until=valid_until,
			device_message_valid_until=valid_until,
		)

		# Should not be shown (expired)
		assert first == []
		# Should be shown
		if user_logged_in:
			assert second == ["user"]
		else:
			assert second == ["device"]
