# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
opsiclientd.posix
"""

from typing import Callable

from OPSI.System import get_subprocess_environment  # type: ignore[import]
from ptyprocess import PtyProcess  # type: ignore[import]


def start_pty(shell: str = "bash", lines: int = 30, columns: int = 120) -> tuple[int, Callable, Callable, Callable, Callable]:
	sp_env = get_subprocess_environment()
	sp_env.update({"TERM": "xterm-256color"})

	proc = PtyProcess.spawn([shell], dimensions=(lines, columns), env=sp_env)
	return (proc.pid, proc.read, proc.write, proc.setwinsize, proc.terminate)
