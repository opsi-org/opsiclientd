# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
test_notification_server
"""

import json
import socket
import time

from OPSI.Util.Message import ChoiceSubject  # type: ignore[import]

from opsiclientd.EventConfiguration import EventConfig
from opsiclientd.EventProcessing import EventProcessingThread
from opsiclientd.Events.Basic import Event
from opsiclientd.Events.Utilities.Configs import getEventConfigs

from .utils import default_config  # noqa


def test_notification_server(default_config):  # noqa
	configs = getEventConfigs()
	eventConfig = EventConfig(configs["on_demand"])

	evt = Event(eventConfig=eventConfig, eventInfo={})
	ept = EventProcessingThread(opsiclientd=None, event=evt)
	ept.startNotificationServer()
	ept._messageSubject.setMessage("pytest")

	choiceSubject = ChoiceSubject(id="choice")
	choiceSubject.setChoices(["abort", "start"])
	choiceSubject.pyTestDone = False

	def abortActionCallback(_choiceSubject):
		pass

	def startActionCallback(_choiceSubject):
		_choiceSubject.pyTestDone = True

	choiceSubject.setCallbacks([abortActionCallback, startActionCallback])
	ept._notificationServer.addSubject(choiceSubject)
	sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	sock.connect(("127.0.0.1", ept.notificationServerPort))
	try:
		data = json.loads(sock.recv(10 * 1024))
		ids = []
		for subject in data.get("params")[0]:
			ids.append(subject["id"])
		assert "choice" in ids, "subject id choice not received"
		rpc1 = {"id": 1, "method": "setSelectedIndexes", "params": ["choice", 1]}
		rpc2 = {"id": 2, "method": "selectChoice", "params": ["choice"]}
		sock.send((json.dumps(rpc1) + "\r\n" + json.dumps(rpc2) + "\r\n").encode("utf-8"))
		time.sleep(1)
		assert choiceSubject.pyTestDone is True, "selectChoice did not set pyTestDone on choiceSubject"
	finally:
		sock.close()
		ept.stopNotificationServer()
