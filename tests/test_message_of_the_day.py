from datetime import datetime, timedelta
from pathlib import Path

from OPSI import System  # type: ignore[import]

from opsiclientd.Config import Config
from opsiclientd.ControlServer import OpsiclientdRpcInterface
from opsiclientd.Opsiclientd import Opsiclientd, state

from .utils import default_config

config = Config()


class FakeOpsiclientd(Opsiclientd):
	def showPopup(
		self,
		message: str,
		mode: str = "prepend",
		addTimestamp: bool = True,
		displaySeconds: int = 0,
		link_handling: str = "no",
		session: str | None = None,
	) -> None:
		pass


def test_motd_update(default_config: None, tmp_path: Path) -> None:
	ocd = FakeOpsiclientd()
	controlServer = OpsiclientdRpcInterface(ocd)
	state._stateFile = tmp_path / "state_file.json"
	user_logged_in = System.getActiveSessionInformation()
	first = controlServer.messageOfTheDayUpdated(user_message="Test message user", device_message="Test message device")
	second = controlServer.messageOfTheDayUpdated(user_message="Test message user", device_message="Test message device")
	if user_logged_in:
		assert first == "user"  # should be shown
	else:
		assert first == "device"
	assert second is None  # should not be shown (same hash)


def test_motd_update_valid_until(default_config: None, tmp_path: Path) -> None:
	ocd = FakeOpsiclientd()
	controlServer = OpsiclientdRpcInterface(ocd)
	state._stateFile = tmp_path / "state_file.json"
	user_logged_in = System.getActiveSessionInformation()
	valid_until = (datetime.now() - timedelta(days=1)).isoformat()
	first = controlServer.messageOfTheDayUpdated(
		user_message="1", device_message="1", user_message_valid_until=valid_until, device_message_valid_until=valid_until
	)
	valid_until = (datetime.now() + timedelta(days=1)).isoformat()
	second = controlServer.messageOfTheDayUpdated(
		user_message="2", device_message="2", user_message_valid_until=valid_until, device_message_valid_until=valid_until
	)
	assert first is None  # should not be shown (same hash)
	if user_logged_in:
		assert second == "user"  # should be shown
	else:
		assert second == "device"
