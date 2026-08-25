# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2026 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from opsiclientd import utils


@pytest.fixture
def mocked_winreg(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
	hkey = object()
	open_key = MagicMock()
	open_key.return_value.__enter__.return_value = hkey
	winreg = SimpleNamespace(
		HKEY_LOCAL_MACHINE=1,
		KEY_READ=2,
		KEY_WOW64_32KEY=4,
		KEY_WOW64_64KEY=8,
		OpenKeyEx=open_key,
		QueryValueEx=MagicMock(return_value=("value", 1)),
	)
	monkeypatch.setattr(utils, "RUNNING_ON_WINDOWS", True)
	monkeypatch.setattr(utils, "winreg", winreg, raising=False)
	return winreg


@pytest.mark.parametrize(("registry_view", "view_flag"), [(32, 4), (64, 8)])
def test_get_registry_value_explicit_view(mocked_winreg: SimpleNamespace, registry_view: int, view_flag: int) -> None:
	assert utils.get_registry_value("sub-key", "name", registry_view=registry_view) == "value"  # ty: ignore[invalid-argument-type]
	mocked_winreg.OpenKeyEx.assert_called_once_with(1, "sub-key", 0, 2 | view_flag)


@pytest.mark.parametrize(("architecture", "view_flag"), [("32bit", 4), ("64bit", 8)])
def test_get_registry_value_native_view(
	monkeypatch: pytest.MonkeyPatch, mocked_winreg: SimpleNamespace, architecture: str, view_flag: int
) -> None:
	monkeypatch.setattr(utils.platform, "architecture", lambda: (architecture, ""))

	assert utils.get_registry_value("sub-key", "name") == "value"
	mocked_winreg.OpenKeyEx.assert_called_once_with(1, "sub-key", 0, 2 | view_flag)


def test_get_registry_value_invalid_view(mocked_winreg: SimpleNamespace) -> None:
	with pytest.raises(ValueError, match="registry_view must be 32, 64 or None"):
		utils.get_registry_value("sub-key", "name", registry_view=16)  # ty: ignore[invalid-argument-type]
