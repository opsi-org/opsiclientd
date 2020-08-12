# -*- coding: utf-8 -*-

import platform

RUNNING_ON_WINDOWS = (platform.system().lower() == 'windows')
RUNNING_ON_LINUX = (platform.system().lower() == 'linux')
RUNNING_ON_DARWIN = RUNNING_ON_MACOS = (platform.system().lower() == 'darwin')
