# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from ptyprocess import PtyProcess

from OPSI.System import get_subprocess_environment


def start_pty(shell="bash", lines=30, columns=120):
	sp_env = get_subprocess_environment()
	sp_env.update({"TERM": "xterm-256color"})

	proc = PtyProcess.spawn([shell], dimensions=(lines, columns), env=sp_env)
	return (proc.read, proc.write, proc.terminate)
