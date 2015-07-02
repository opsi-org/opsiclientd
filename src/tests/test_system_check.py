# -*- coding: utf-8 -*-

import os
import unittest
from context import SystemCheck as syscheck


class RunningOnWindowsTest(unittest.TestCase):
    def test_system_determining(self):
        if os.name == 'nt':
            self.assertTrue(syscheck.RUNNING_ON_WINDOWS)
        else:
            self.assertFalse(syscheck.RUNNING_ON_WINDOWS)


if __name__ == '__main__':
    unittest.main()
