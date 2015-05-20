#! /usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
from cx_Freeze import setup, Executable

buildOptions = {
    "packages": [
        "OPSI",
        "ocdlib",
        "apsw",
        "csv",
    ],
    "excludes": [],
    "include_files": [
        ("/usr/lib/x86_64-linux-gnu/librsync.so.1", "librsync.so.1"), # TODO: make this dynamic
    ],
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
