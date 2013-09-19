#! python
# -*- coding: utf-8 -*-
"""
opsi client daemon (opsiclientd)

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
import os
import sys

from OPSI.Logger import Logger, LOG_WARNING

if os.name == 'nt':
	from ocdlib.Windows import OpsiclientdInit
elif os.name == 'posix':
	from ocdlib.Posix import OpsiclientdInit
else:
	raise NotImplementedError('Trying to run under an unsupported OS.')


if (__name__ == "__main__"):
	logger = Logger()
	moduleName = u' %-30s' % (u'opsiclientd', )
	logger.setLogFormat(u'[%l] [%D] [' + moduleName + u'] %M   (%F|%N)')
	logger.setConsoleLevel(LOG_WARNING)

	try:
		OpsiclientdInit()
	except SystemExit:
		pass
	except Exception as exception:
		logger.logException(exception)
		print >> sys.stderr, u"ERROR:", unicode(exception)
		sys.exit(1)

	sys.exit(0)
