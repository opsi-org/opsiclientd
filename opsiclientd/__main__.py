# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
opsi client daemon (opsiclientd)
"""

import os
import platform
import sys
import warnings
from datetime import datetime

import sqlalchemy  # type: ignore[import]

# STARTUP_LOG = r"c:\opsi.org\log\opsiclientd_startup.log"
STARTUP_LOG: str | None = None


def opsiclientd_rpc() -> None:
	from opsiclientd.opsiclientdrpc import main as _main

	_main()
	sys.exit(0)


def action_processor_starter() -> None:
	from opsiclientd.actionprocessorstarter import main as _main

	_main()
	sys.exit(0)


def opsiclientd() -> None:
	# Disable sqlalchemy 2.0 deprecation warnings
	sqlalchemy.util.deprecations.SILENCE_UBER_WARNING = True
	if getattr(sys, "frozen", False):
		# Disable resource warnings if frozen
		warnings.simplefilter("ignore", ResourceWarning)

	if platform.system().lower() == "windows":
		if STARTUP_LOG and os.path.isdir(os.path.dirname(STARTUP_LOG)):
			with open(STARTUP_LOG, "w", encoding="utf-8") as file:
				file.write(f"{datetime.now()} opsiclientd startup\n")
		from opsiclientd.windows.main import main as _main
	elif platform.system().lower() in ("linux", "darwin"):
		from opsiclientd.posix.main import main as _main
	else:
		raise NotImplementedError(f"OS {os.name} not supported.")

	try:
		_main()
		sys.exit(0)
	except Exception as err:
		print(f"ERROR: {err}", file=sys.stderr)
		try:
			from opsicommon.logging import logger  # type: ignore[import]

			logger.critical(err, exc_info=True)
		except Exception as log_err:
			print(f"ERROR: {log_err}", file=sys.stderr)
		sys.exit(1)


def main() -> None:
	name = os.path.splitext(os.path.basename(sys.argv[0]))[0].lower()
	if name == "opsiclientd_rpc":
		return opsiclientd_rpc()
	if name == "action_processor_starter":
		return action_processor_starter()
	return opsiclientd()
