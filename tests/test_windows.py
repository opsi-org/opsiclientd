# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
test_windows
"""

from __future__ import annotations

from pathlib import Path

import pytest
from opsi.process import run_command


@pytest.mark.windows
def test_get_link_target(tmp_path: Path) -> None:
	from opsiclientd.windows import get_link_target

	test_dir = tmp_path / "test_dir" / "sub"
	test_dir.mkdir(parents=True)
	link = tmp_path / "link"
	run_command(["mklink", "/j", str(link), str(test_dir)], timeout=10)
	target = get_link_target(link)
	assert target == test_dir
