#! /usr/bin/env python
# -*- coding: utf-8 -*-

import unittest

from ocdlib.Exceptions import OpsiclientdError


class ExceptionsTestCase(unittest.TestCase):
	def testGivingMessage(self):
		error = OpsiclientdError()
		self.assertTrue(OpsiclientdError.ExceptionShortDescription in repr(error))

		errorWithMessage = OpsiclientdError("Something failed.")
		self.assertFalse(OpsiclientdError.ExceptionShortDescription in repr(errorWithMessage))
		self.assertTrue("Something failed." in repr(errorWithMessage))


if __name__ == '__main__':
	unittest.main()
