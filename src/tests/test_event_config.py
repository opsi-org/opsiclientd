#! /usr/bin/env python
#-*- coding: utf-8 -*-

import unittest

from ocdlib.EventConfiguration import EventConfig


class EventConfigTestCase(unittest.TestCase):
    def testCreatingNewEventConfig(self):
        config = EventConfig("testevent")


if __name__ == '__main__':
    unittest.main()
