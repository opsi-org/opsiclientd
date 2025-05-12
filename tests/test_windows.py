# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2025 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0-only

"""
test_windows
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from opsiclientd.windows import get_link_target


def test_get_link_target(tmp_path: Path) -> None:
	test_dir = tmp_path / "test_dir" / "sub"
	test_dir.mkdir(parents=True)
	link = tmp_path / "link"
	subprocess.run(f'mklink /j "{link}" "{str(test_dir)}"', check=True, shell=True)
	target = get_link_target(link)
	assert target == test_dir
