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

from OPSI.Logger import Logger
from OPSI.Types import forceUnicode

logger = Logger()


class OpsiclientdError(Exception):
	ExceptionShortDescription = u"Opsiclientd error"

	def __init__(self, message=u''):
		self._message = forceUnicode(message)

	def __unicode__(self):
		if self._message:
			return u"%s: %s" % (self.ExceptionShortDescription, self._message)
		else:
			return u"%s" % self.ExceptionShortDescription

	def __repr__(self):
		return self.__unicode__().encode("ascii", "replace")

	__str__ = __repr__


class CanceledByUserError(OpsiclientdError):
	""" Exception raised if user cancels operation. """
	ExceptionShortDescription = "Canceled by user error"
