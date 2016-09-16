#! /usr/bin/env python
# -*- coding: utf-8 -*-

import unittest

from ocdlib.EventConfiguration import EventConfig


class EventConfigTestCase(unittest.TestCase):
    def testCreatingNewEventConfig(self):
        config = EventConfig("testevent")

    def testAttributesForWhiteAndBlackListExist(self):
        config = EventConfig("testevent")

        assert hasattr(config, 'excludeProductGroupIds')
        assert hasattr(config, 'includeProductGroupIds')

if __name__ == '__main__':
    unittest.main()
