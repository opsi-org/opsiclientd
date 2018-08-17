#! /usr/bin/env python
# -*- coding: utf-8 -*-

# This file is part of python-opsi.
# Copyright (C) 2015-2017 uib GmbH <info@uib.de>

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

import os
import platform
import sys

import duplicity  # to make sure this is installed
from cx_Freeze import setup, Executable

from setuplib import getVersion

buildOptions = {
    "packages": [
        "OPSI",
        "OPSI.web2.dav.method",
        "ocdlib",
        "apsw",
        "csv",
        "encodings",
        "duplicity",
        "twisted",
        "zope.interface",  # required by twisted
        "tornado",
    ],
    "excludes": [
        "Tkconstants",
        "Tkinter",
        "tcl",
        "_imagingtk",
        "PIL._imagingtk",
        "ImageTk",
        "PIL.ImageTk",
        "FixTk",
        "collections.sys",  # Fix for https://bitbucket.org/anthony_tuininga/cx_freeze/issues/127/collectionssys-error
        "collections.abc",  # Fix for https://bitbucket.org/anthony_tuininga/cx_freeze/issues/127/collectionssys-error
    ],
    "include_files": [],
    "namespace_packages": [
        'zope',
    ]
}

distribution, version, _ = platform.linux_distribution()
print("Running on {!r} version {!r}".format(distribution, version))
if distribution.lower().strip() == 'debian' and version.startswith('8'):
    # Required by Debian 8 - see https://github.com/pyca/cryptography/issues/2039#issuecomment-132225074
    buildOptions['packages'].append('cffi')
    buildOptions['packages'].append('Crypto.Cipher.AES')
    buildOptions['packages'].append('cryptography')
elif distribution.lower().strip() == 'debian' and version.startswith('9'):
    buildOptions['packages'].append('cffi')
    buildOptions['packages'].append('Crypto.Cipher.AES')
    buildOptions['packages'].append('cryptography')
elif distribution.lower().strip() == 'suse linux enterprise server' and version.startswith('12'):
    buildOptions['packages'].append('distutils')
    buildOptions['packages'].append('cffi')
    buildOptions['packages'].append('Crypto.Cipher.AES')
    buildOptions['packages'].append('cryptography')
elif distribution.lower().strip() == 'opensuse' and version.startswith('42'):
    buildOptions['packages'].append('cffi')
    buildOptions['packages'].append('Crypto.Cipher.AES')
    buildOptions['packages'].append('cryptography')
elif distribution.lower().strip() == 'ubuntu' and version.startswith('16.'):
    buildOptions['packages'].append('cffi')
    buildOptions['packages'].append('Crypto.Cipher.AES')
    buildOptions['packages'].append('cryptography')
    buildOptions['packages'].append('pkg_resources._vendor.packaging')
    buildOptions['packages'].append('pkg_resources._vendor.six')

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

localDirectory = os.path.dirname(__file__)

executables = [
    Executable(os.path.join(localDirectory, 'scripts', 'opsiclientd'), 'Console', targetName='opsiclientd')
]

setup(name='opsiclientd',
      version=opsiClientDeamonVersion,
      description=('opsi client daemon - opsiclientd is part of the '
                   'desktop management solution opsi (open pc server '
                   'integration) - http://www.opsi.org'),
      options={"build_exe": buildOptions},
      executables=executables)
