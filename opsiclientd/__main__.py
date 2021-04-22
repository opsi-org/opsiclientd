# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
opsi client daemon (opsiclientd)
"""

import os
import sys
import platform

def opsiclientd_rpc():
	from opsiclientd.opsiclientdrpc import main as _main # pylint: disable=import-outside-toplevel
	_main()

def action_processor_starter():
	from opsiclientd.actionprocessorstarter import main as _main # pylint: disable=import-outside-toplevel
	_main()

def opsiclientd():
	from opsicommon.logging import logger # pylint: disable=import-outside-toplevel
	_main = None
	if platform.system().lower() == 'windows':
		from opsiclientd.windows.main import main as _main # pylint: disable=import-outside-toplevel
	elif platform.system().lower() in ('linux', 'darwin'):
		from opsiclientd.posix.main import main as _main # pylint: disable=import-outside-toplevel
	else:
		raise NotImplementedError(f"OS {os.name} not supported.")
	try:
		_main()
	except Exception as err: # pylint: disable=broad-except
		logger.critical(err, exc_info=True)

def main():
	name = os.path.splitext(os.path.basename(sys.argv[0]))[0].lower()
	if name == "opsiclientd_rpc":
		return opsiclientd_rpc()
	if name == "action_processor_starter":
		return action_processor_starter()
	return opsiclientd()
