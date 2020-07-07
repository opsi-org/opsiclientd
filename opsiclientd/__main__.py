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
import opsicommon.logging

def opsiclientd_rpc():
	from opsiclientd.opsiclientdrpc import main
	main()

def action_processor_starter():
	from opsiclientd.actionprocessorstarter import main
	main()

def opsiclientd():
	if os.name == 'nt':
		from opsiclientd.Windows import OpsiclientdInit
	elif os.name == 'posix':
		from opsiclientd.Posix import OpsiclientdInit
	else:
		raise NotImplementedError("OS %s not supported." % os.name)

	opsicommon.logging.set_format(opsicommon.logging.DEFAULT_COLORED_FORMAT)
	OpsiclientdInit()

def main():
	name = os.path.splitext(os.path.basename(sys.argv[0]))[0].lower()
	if name == "opsiclientd_rpc":
		return opsiclientd_rpc()
	elif name == "action_processor_starter":
		return action_processor_starter()
	return opsiclientd()
