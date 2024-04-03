# -*- coding: utf-8 -*-

# opsiclientd is part of the desktop management solution opsi http://www.opsi.org
# Copyright (c) 2010-2021 uib GmbH <info@uib.de>
# This code is owned by the uib GmbH, Mainz, Germany (uib.de). All rights reserved.
# License: AGPL-3.0
"""
test_exceptions
"""

from typing import Type

import pytest

from opsiclientd.Exceptions import OpsiclientdError


@pytest.mark.parametrize("testClass", [OpsiclientdError])
@pytest.mark.parametrize("errorMessage", [None, "Something failed."])
def testGivingMessages(testClass: Type[OpsiclientdError], errorMessage: str | None) -> None:
	if errorMessage:
		error = testClass(errorMessage)
	else:
		error = testClass()
	assert testClass.ExceptionShortDescription in repr(error)
	if errorMessage:
		assert errorMessage in repr(error)
