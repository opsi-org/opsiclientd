#! env python
# -*- coding: utf-8 -*-
"""
notifier

notifier is part of the desktop management solution opsi
(open pc server integration) http://www.opsi.org

Copyright (C) 2014 uib GmbH

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

:copyright:	uib GmbH <info@uib.de>
:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU General Public License version 2
"""

__version__ = '4.0'

import sys
import os
import getopt
import locale

from OPSI.Types import forceInt, forceFilename, forceUnicode
from OPSI.Util.Message import NotificationClient, SubjectsObserver
from OPSI.Logger import Logger, LOG_NONE, LOG_DEBUG

encoding = locale.getpreferredencoding()
argv = [unicode(arg, encoding) for arg in sys.argv]

try:
	language = locale.getdefaultlocale()[0].split('_')[0]
except Exception, e:
	language = 'en'

logger = Logger()
logFile = u''
host = u'127.0.0.1'
port = 0
notificationClientId = None


class OpsiDialogWindow(SubjectsObserver):
	def __init__(self):
		self._notificationClient = None
		if port:
			self._notificationClient = NotificationClient(host, port, self, notificationClientId)
			self._notificationClient.addEndConnectionRequestedCallback(self.close)

	def close(self):
		logger.notice(u"OpsiDialogWindow.close()")

	def setStatusMessage(self, message):
		self.messageChanged({'id': "status", 'type': "faketype"}, message)

	def messageChanged(self, subject, message):
		subjectId = subject.get('id')
		subjectType = subject.get('type')
		logger.info(u"message changed, subjectId: {0}, subjectType {1}, message: {2}".format(subjectId, subjectType, message))

	def selectedIndexesChanged(self, subject, selectedIndexes):
		pass

	def choicesChanged(self, subject, choices):
		pass

	def progressChanged(self, subject, state, percent, timeSpend, timeLeft, speed):
		subjectId = subject.get('id')
		subjectType = subject.get('type')
		# TODO: this
		for (item, values) in self.skin.items():
			if (values.get('type') != u'progressbar'):
				continue
			ctrlId = values.get('ctrlId')
			if not ctrlId:
				continue
			if (values.get('subjectId') == subjectId) or (not values.get('subjectId') and (values.get('subjectType') == subjectType)):
				logger.info(u"progress changed, subjectId: %s, ctrlId: %s, percent: %s" % (subjectId, ctrlId, percent))
				values['ctrl'].SetRange(0, 100)
				values['ctrl'].SetPos(int(percent))

	def subjectsChanged(self, subjects):
		logger.info(u"subjectsChanged(%s)" % subjects)
		choices = {}
		for subject in subjects:
			if (subject['class'] == 'MessageSubject'):
				self.messageChanged(subject, subject['message'])
			if (subject['class'] == 'ChoiceSubject'):
				subjectId = subject.get('id')
				choices[subjectId] = subject.get('choices', [])

		logger.debug(u"subjectsChanged() ended")

def usage():
	print u"\nUsage: %s [-h <host>] [-p <port>]" % os.path.basename(argv[0])
	print u"Options:"
	print u"  -h, --host      Notification server host (default: %s)" % host
	print u"  -p, --port      Notification server port (default: %s)" % port
	print u"  -i, --id        Notification client id (default: %s)" % notificationClientId


if (__name__ == "__main__"):
	# If you write to stdout when running from pythonw.exe program will die !!!
	logger.setConsoleLevel(LOG_NONE)
	exception = None

	try:
		logger.notice(u"Commandline: %s" % ' '.join(argv))

		# Process command line arguments
		try:
			(opts, args) = getopt.getopt(argv[1:], "h:p:s:i:l:", ["host=", "port=", "id=", "log-file="])
		except getopt.GetoptError:
			usage()
			sys.exit(1)

		for (opt, arg) in opts:
			logger.info(u"Processing option %s:%s" % (opt, arg))
			if   opt in ("-a", "--host"):
				host = forceUnicode(arg)
			elif opt in ("-p", "--port"):
				port = forceInt(arg)
			elif opt in ("-i", "--id"):
				notificationClientId = forceUnicode(arg)
			elif opt in ("-l", "--log-file"):
				logFile = forceFilename(arg)
				if os.path.exists(logFile):
					logger.notice(u"Deleting old log file: %s" % logFile)
					os.unlink(logFile)
				logger.notice(u"Opening log file: %s" % logFile)
				logger.setLogFile(logFile)
				logger.setFileLevel(LOG_DEBUG)

		logger.notice(u"Host: %s, port: %s, logfile: %s" % (host, port, logFile))
		w = OpsiDialogWindow()
		w.CreateWindow()
	except Exception as e:
		exception = e

	if exception:
		logger.logException(exception)
		tb = sys.exc_info()[2]
		while (tb != None):
			f = tb.tb_frame
			c = f.f_code
			print >> sys.stderr, u"     line %s in '%s' in file '%s'" % (tb.tb_lineno, c.co_name, c.co_filename)
			tb = tb.tb_next
		print >> sys.stderr, u"ERROR: %s" % exception
		sys.exit(1)

	sys.exit(0)
