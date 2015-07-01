#! /usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of python-opsi.
# Copyright (C) 2015 uib GmbH <info@uib.de>

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.

# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""
Setup script for freezing the opsiclientd with cx_Freeze.

:author: Niko Wenselowski <n.wenselowski@uib.de>
:license: GNU Affero General Public License version 3
"""

from __future__ import absolute_import

import os
import sys

import duplicity
from cx_Freeze import setup, Executable

from .setuplib import getVersion

buildOptions = {
    "packages": [
        "OPSI",
        "OPSI.web2.dav.method",
        "ocdlib",
        "apsw",
        "csv",
        "encodings",
    ],
    "excludes": [],
    "include_files": [],
    "compressed": True,
}


localDirectory = os.path.dirname(__file__)

opsiClientDeamonVersion = None
fileWithVersion = os.path.join(localDirectory, 'ocdlib', '__init__.py')
with open(fileWithVersion, 'r') as f:
    for line in f:
        if "__version__" in line:
            opsiClientDeamonVersion = line.split('=', 1)[1].strip()[1:-1]
            break

if not opsiClientDeamonVersion:
    raise Exception("Failed to find version.")


if os.path.exists("/usr/lib/x86_64-linux-gnu/librsync.so.1"):
    buildOptions['include_files'].append(("/usr/lib/x86_64-linux-gnu/librsync.so.1", "librsync.so.1"))
elif os.path.exists("/usr/lib/librsync.so.1"):
    buildOptions['include_files'].append(("/usr/lib/librsync.so.1", "librsync.so.1"))
elif os.path.exists("/usr/lib64/librsync.so.1"):
    buildOptions['include_files'].append(("/usr/lib64/librsync.so.1", "librsync.so.1"))
else:
    print("Warning: could not find librsync.so.1!")

if os.path.exists('/usr/lib64/librsync.so.1.0.2'):
    buildOptions['include_files'].append(("/usr/lib64/librsync.so.1.0.2", "librsync.so.1.0.2"))
elif os.path.exists('/usr/lib/librsync.so.1.0.2'):
    buildOptions['include_files'].append(("/usr/lib/librsync.so.1.0.2", "librsync.so.1.0.2"))

buildFreeVersion = False
if '--free' in sys.argv:
    buildFreeVersion = True
    sys.argv.remove('--free')

opsiclientdDescription = "opsi client daemon"
if os.path.exists("ocdlibnonfree") and not buildFreeVersion:
    buildOptions['packages'].append("ocdlibnonfree")
    opsiclientdDescription = u"opsi client daemon (full)"
else:
    buildOptions['excludes'].append("ocdlibnonfree")

opsiClientDeamonVersion = getVersion()
print("Building {0} (Version {1})".format(opsiclientdDescription,
                                          opsiClientDeamonVersion))

executables = [
    Executable(os.path.join(localDirectory, 'scripts', 'opsiclientd'), 'Console', targetName='opsiclientd')
]

setup(name='opsiclientd',
      version=opsiClientDeamonVersion,
      description=('opsi client daemon - opsiclientd is part of the '
                   'desktop management solution opsi (open pc server '
                   'integration) - http://www.opsi.org'),
      options={"build_exe": buildOptions},
      executables=executables
)
