# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi
# (open pc server integration) http://www.opsi.org
# Copyright (C) 2010-2018 uib GmbH <info@uib.de>

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
Non-standard exceptions.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
:license: GNU Affero General Public License version 3
"""

#from OPSI.Logger import Logger
from opsicommon.logging import logger
from OPSI.Types import forceUnicode

#logger = Logger()


class OpsiclientdError(Exception):
	ExceptionShortDescription = u"Opsiclientd error"

	def __init__(self, message=u''):
		self._message = forceUnicode(message)

	def __str__(self):
		_str = self.ExceptionShortDescription
		if self._message:
			_str += f": {self._message}"
		return _str
	
	__repr__ = __str__


class CanceledByUserError(OpsiclientdError):
	""" Exception raised if user cancels operation. """
	ExceptionShortDescription = "Canceled by user error"

class ConfigurationError(OpsiclientdError):
	""" Exception raised if a configuration is invalid or missing. """
	ExceptionShortDescription = "Configuration error"
