# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# All rights reserved.
# License: AGPL-3.0
"""
Non-standard exceptions.
"""

from OPSI.Types import forceUnicode

class OpsiclientdError(Exception):
	ExceptionShortDescription = "Opsiclientd error"

	def __init__(self, message=''):
		Exception.__init__(self)
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
