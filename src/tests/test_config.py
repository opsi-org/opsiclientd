#!/usr/bin/env python
#-*- coding: utf-8 -*-

from __future__ import unicode_literals

import unittest

from ocdlib.Config import Config,


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.config = Config()

    def tearDown(self):
        self.config._reset()
        del self.config

    def testGettingUnknownSectionFails(self):
        self.assertRaises(ValueError, self.config.get, 'nothing', 'bla')

    def testGettingUnknownOptionFails(self):
        self.assertRaises(ValueError, self.config.get, 'global', 'non_existing_option')
