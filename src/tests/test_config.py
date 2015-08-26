#!/usr/bin/env python
#-*- coding: utf-8 -*-

from __future__ import unicode_literals

import unittest

from ocdlib.Config import (Config,
    SectionNotFoundException, NoConfigOptionFoundException)


class ConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.config = Config()

    def tearDown(self):
        self.config._reset()
        del self.config

    def testGettingUnknownSectionFails(self):
        self.assertRaises(SectionNotFoundException, self.config.get, 'nothing', 'bla')

    def testGettingUnknownOptionFails(self):
        self.assertRaises(NoConfigOptionFoundException, self.config.get, 'global', 'non_existing_option')
