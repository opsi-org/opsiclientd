from pathlib import Path

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
	assert controlServer.messageOfTheDayUpdated(user_message="Test message") == "user"  # should be shown
	assert controlServer.messageOfTheDayUpdated(user_message="Test message") is None  # should not be shown (same hash)
