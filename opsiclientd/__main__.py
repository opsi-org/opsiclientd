#! /usr/bin/python
# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2019 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
opsi client daemon (opsiclientd)

:copyright: uib GmbH <info@uib.de>
:license: GNU Affero General Public License version 3
"""

import os
import sys
import platform

def opsiclientd_rpc():
	from opsiclientd.opsiclientdrpc import main as _main
	_main()

def action_processor_starter():
	from opsiclientd.actionprocessorstarter import main as _main
	_main()

def opsiclientd():
	from opsicommon.logging import logger
	_main = None
	if platform.system().lower() == 'windows':
		from opsiclientd.windows.main import main as _main
	elif platform.system().lower() == 'linux':
		from opsiclientd.linux.main import main as _main
	elif platform.system().lower() == 'darwin':
		from opsiclientd.darwin.main import main as _main
	else:
		raise NotImplementedError("OS %s not supported." % os.name)	
	try:
		_main()
	except Exception as e:
		logger.critical(e, exc_info=True)

def main():
	name = os.path.splitext(os.path.basename(sys.argv[0]))[0].lower()
	if name == "opsiclientd_rpc":
		return opsiclientd_rpc()
	elif name == "action_processor_starter":
		return action_processor_starter()
	return opsiclientd()
