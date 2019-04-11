# -*- coding: utf-8 -*-

import pytest
from ocdlib.Exceptions import OpsiclientdError


@pytest.mark.parametrize("testClass", [OpsiclientdError])
@pytest.mark.parametrize("errorMessage", [None, "Something failed."])
def testGivingMessages(testClass, errorMessage):
	if errorMessage:
		error = testClass(errorMessage)
	else:
		error = testClass()

	assert testClass.ExceptionShortDescription in repr(error)
	if errorMessage:
		assert errorMessage in repr(error)
