# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2024 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

"""
Notification client for the opsiclientd.
"""

__version__ = "4.0"

import getopt
import locale
import os
import sys

from OPSI.Logger import LOG_DEBUG, LOG_NONE, Logger
from OPSI.Types import forceFilename, forceInt, forceUnicode
from OPSI.Util.Message import NotificationClient, SubjectsObserver

encoding = locale.getpreferredencoding()
argv = sys.argv

logger = Logger()


class OpsiDialogWindow(SubjectsObserver):
	def __init__(self, port=0, host="127.0.0.1", notificationClientId=None):
		self._notificationClient = None
		if port:
			self._notificationClient = NotificationClient(host, port, self, notificationClientId)
			self._notificationClient.addEndConnectionRequestedCallback(self.close)

	def close(self):
		logger.notice("OpsiDialogWindow.close()")

	def setStatusMessage(self, message):
		self.messageChanged({"id": "status", "type": "faketype"}, message)

	def messageChanged(self, subject, message):
		subjectId = subject.get("id")
		subjectType = subject.get("type")
		logger.info("message changed, subjectId: %s, subjectType %s, message: %s", subjectId, subjectType, message)

	def selectedIndexesChanged(self, subject, selectedIndexes):
		pass

	def choicesChanged(self, subject, choices):
		pass

	def progressChanged(self, subject, state, percent, timeSpend, timeLeft, speed):
		subjectId = subject.get("id")
		subjectType = subject.get("type")
		# TODO: this
		for item, values in self.skin.items():
			if values.get("type") != "progressbar":
				continue
			ctrlId = values.get("ctrlId")
			if not ctrlId:
				continue
			if (values.get("subjectId") == subjectId) or (not values.get("subjectId") and (values.get("subjectType") == subjectType)):
				logger.info("progress changed, subjectId: %s, ctrlId: %s, percent: %s" % (subjectId, ctrlId, percent))
				values["ctrl"].SetRange(0, 100)
				values["ctrl"].SetPos(int(percent))

	def subjectsChanged(self, subjects):
		logger.info("subjectsChanged(%s)" % subjects)
		choices = {}
		for subject in subjects:
			if subject["class"] == "MessageSubject":
				self.messageChanged(subject, subject["message"])
			if subject["class"] == "ChoiceSubject":
				subjectId = subject.get("id")
				choices[subjectId] = subject.get("choices", [])

		logger.debug("subjectsChanged() ended")


if __name__ == "__main__":
	from OPSI.Util import argparse

	logger.setConsoleLevel(LOG_DEBUG)
	exception = None

	try:
		parser = argparse.ArgumentParser()
		parser.add_argument("--host", help="Notification server host", default="127.0.0.1")
		parser.add_argument("-p", "--port", type=int, help="Notification server port", default=0)
		parser.add_argument("-i", "--id", dest="notificationClientId", help="Notification client id", default=None)
		parser.add_argument("-l", "--log-file", dest="logFile", help="Log file to use.")

		args = parser.parse_args()
		args.port = forceUnicode(args.port)
		args.notificationClientId = forceUnicode(args.notificationClientId)

		if args.logFile:
			logFile = forceFilename(args.logFile)
			# TODO: logrotate?
			if os.path.exists(logFile):
				logger.notice("Deleting old log file: %s" % logFile)
				os.unlink(logFile)
			logger.notice("Setting log file: %s" % logFile)
			logger.setLogFile(logFile)
			logger.setFileLevel(LOG_DEBUG)

		w = OpsiDialogWindow()
	except Exception as err:
		logger.error(err, exc_info=True)
		tb = sys.exc_info()[2]
		while tb is not None:
			f = tb.tb_frame
			c = f.f_code
			print("     line %s in '%s' in file '%s'" % (tb.tb_lineno, c.co_name, c.co_filename), file=sys.stderr)
			tb = tb.tb_next
		print(f"ERROR: {err}", file=sys.stderr)
		sys.exit(1)

	sys.exit(0)
