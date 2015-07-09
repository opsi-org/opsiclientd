#! /usr/bin/env python
# -*- coding: utf-8 -*-
"""
ocdlibnonfree.EventProcessing

opsiclientd is part of the desktop management solution opsi
(open pc server integration) http://www.opsi.org

Copyright (C) 2010-2015 uib GmbH

http://www.uib.de/

All rights reserved.

:copyright: uib GmbH <info@uib.de>
:author: Jan Schneider <j.schneider@uib.de>
"""

# Imports
import base64
import filecmp
import os
import shutil
import sys
from hashlib import md5

# Twisted imports
from twisted.conch.ssh import keys

# OPSI imports
from OPSI.Logger import *
from OPSI.Util import *
from OPSI.Util.Message import *
from OPSI.Types import *
from OPSI import System
from OPSI.Object import *

from ocdlib.Exceptions import *
from ocdlib.Events import *
from ocdlib.OpsiService import ServiceConnection
if (os.name == 'nt'):
	from ocdlib.Windows import *
if (os.name == 'posix'):
	from ocdlib.Posix import *
from ocdlib.Localization import _, setLocaleDir, getLanguage
from ocdlib.Config import Config
import ocdlib.EventProcessing

logger = Logger()
config = Config()
