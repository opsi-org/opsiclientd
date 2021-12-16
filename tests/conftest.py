# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0

from _pytest.logging import LogCaptureHandler

def emit(*args, **kwargs) -> None:  # pylint: disable=unused-argument
	pass
LogCaptureHandler.emit = emit
