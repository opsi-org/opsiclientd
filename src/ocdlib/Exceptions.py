# -*- coding: utf-8 -*-
"""
   = = = = = = = = = = = = = = = = = = = = =
   =   ocdlib.Exceptions                   =
   = = = = = = = = = = = = = = = = = = = = =
   
   opsiclientd is part of the desktop management solution opsi
   (open pc server integration) http://www.opsi.org
   
   Copyright (C) 2010 uib GmbH
   
   http://www.uib.de/
   
   All rights reserved.
   
   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License version 2 as
   published by the Free Software Foundation.
   
   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
   
   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
   
   @copyright:	uib GmbH <info@uib.de>
   @author: Jan Schneider <j.schneider@uib.de>
   @license: GNU General Public License version 2
"""

# OPSI imports
from OPSI.Logger import *
from OPSI.Types import forceUnicode

# Get logger instance
logger = Logger()

class OpsiclientdError(Exception):
	ExceptionShortDescription = u"Opsiclientd error"
	
	def __init__(self, message = u''):
		self._message = forceUnicode(message)
	
	def __unicode__(self):
		if self._message:
			return u"%s: %s" % (self.ExceptionShortDescription, self._message)
		else:
			return u"%s" % self.ExceptionShortDescription
		
	def __repr__(self):
		return self.__unicode__.encode("ascii", "replace")
	
	__str__ = __repr__

class CanceledByUserError(OpsiclientdError):
	""" Exception raised if user cancels operation. """
	ExceptionShortDescription = "Canceled by user error"

class OpsiclientdAuthenticationError(Exception):
	ExceptionShortDescription = u"Opsiclientd authentication error"

class OpsiclientdBadRpcError(Exception):
	ExceptionShortDescription = u"Opsiclientd bad rpc error"

class OpsiclientdRpcError(Exception):
	ExceptionShortDescription = u"Opsiclientd rpc error"












