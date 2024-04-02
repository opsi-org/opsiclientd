from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from unittest.mock import patch

import pytest
from opsicommon.logging import LOG_INFO, use_logging_config

from opsiclientd.Config import Config
from opsiclientd.ControlServer import OpsiclientdRpcInterface
from opsiclientd.Opsiclientd import Opsiclientd, state

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
		sessions: list[str] | None = None,
		desktops: list[str] | None = None,
	) -> None:
		pass


@pytest.mark.parametrize(
	"user_logged_in",
	(False, True),
)
def test_motd_update_without_valid_until(default_config: None, tmp_path: Path, user_logged_in: bool) -> None:  # noqa
	def getActiveSessionInformation():
		if not user_logged_in:
			return []
		return [{"SessionId": 1, "UserName": "testuser"}, {"SessionId": 2, "UserName": "testuser2"}]

	ocd = FakeOpsiclientd()
	controlServer = OpsiclientdRpcInterface(ocd)
	state._stateFile = tmp_path / "state_file.json"

	with use_logging_config(stderr_level=LOG_INFO):
		with patch("opsiclientd.Opsiclientd.System.getActiveSessionInformation", getActiveSessionInformation):
			first = controlServer.messageOfTheDayUpdated(
				user_message="Test message user",
				user_message_valid_until=0,
				device_message="Test message device",
				device_message_valid_until=None,  # type: ignore[arg-type]
			)
			second = controlServer.messageOfTheDayUpdated(user_message="Test message user", device_message="Test message device")
			# First should be shown
			if user_logged_in:
				assert first == ["user"]
			else:
				assert first == ["device"]
			# Second should not be shown (same hash)
			assert second == []


@pytest.mark.parametrize(
	"user_logged_in",
	(False, True),
)
def test_motd_update_valid_until(default_config: None, tmp_path: Path, user_logged_in: bool) -> None:  # noqa
	def getActiveSessionInformation():
		if not user_logged_in:
			return []
		return [{"SessionId": 1, "UserName": "testuser"}, {"SessionId": 2, "UserName": "testuser2"}]

	ocd = FakeOpsiclientd()
	controlServer = OpsiclientdRpcInterface(ocd)
	state._stateFile = tmp_path / "state_file.json"

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
