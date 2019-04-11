#! /usr/bin/env python
# -*- coding: utf-8 -*-

import glob
import os
import shutil
import sys

from distutils.core import setup

RUNS_ON_WINDOWS = sys.platform in ('nt', 'win32')

if RUNS_ON_WINDOWS:
	import py2exe

for d in ('build', 'dist'):
	if os.path.exists(d):
		shutil.rmtree(d)

buildFreeVersion = False
if '--free' in sys.argv:
	buildFreeVersion = True
	sys.argv.remove('--free')

# If run without args, build executables, in quiet mode.
if RUNS_ON_WINDOWS and len(sys.argv) == 1:
	sys.argv.append("py2exe")
	sys.argv.append("-q")


def tree(dst, src):
	unwanted_directories = ('.svn', '.git')
	found_files = []
	for (root, dirs, files) in os.walk(os.path.normpath(src)):
		for unwanted_directory in unwanted_directories:
			if unwanted_directory in dirs:
				dirs.remove(unwanted_directory)

		for unwanted_directory in unwanted_directories:
			if root.endswith(unwanted_directory):
				continue

		newfiles = []
		for f in files:
			if f.endswith('~'):
				continue
			newfiles.append(os.path.join(root, f))

		if not newfiles:
			continue
		found_files.append( (os.path.normpath(os.path.join(dst, root)), newfiles) )

	return found_files

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


class Target:
	def __init__(self, **kw):
		self.__dict__.update(kw)
		self.company_name = "uib GmbH"
		self.copyright = "uib GmbH"
		self.version = opsiClientDeamonVersion


opsiclientdDescription = "opsi client daemon"
packages = ["ocdlib"]
excludes = ["pywin", "pywin.debugger", "pywin.debugger.dbgcon",
	"pywin.dialogs", "pywin.dialogs.list",
	"Tkconstants", "Tkinter", "tcl", "_imagingtk",
	"PIL._imagingtk", "ImageTk", "PIL.ImageTk", "FixTk"
]
#includes = ["_cffi_backend","wmi","csv"]
includes = ["_cffi_backend","wmi","csv","appdirs","packaging",
            "packaging.version","packaging.specifiers",
           "packaging.requirements"]

if os.path.exists("ocdlibnonfree") and not buildFreeVersion:
	packages.append("ocdlibnonfree")
	opsiclientdDescription = u"opsi client daemon (full)"
else:
	excludes.append("ocdlibnonfree")

print "Building %s" % opsiclientdDescription

if RUNS_ON_WINDOWS:
	packages.append("cryptography")

	data_files = [
		('VC90', glob.glob(r'C:\Windows\winsxs\x86_microsoft.vc90.crt_1fc8b3b9a1e18e3b_9.0.21022.8_none_bcb86ed6ac711f91\*.*')),
		('VC90', glob.glob(r'C:\Windows\winsxs\Manifests\x86_microsoft.vc90.crt_1fc8b3b9a1e18e3b_9.0.21022.8_none_bcb86ed6ac711f91.manifest')),
		('notifier',                      [	'windows\\helpers\\notifier\\event.ini',
							'windows\\helpers\\notifier\\action.ini',
							'windows\\helpers\\notifier\\userlogin.ini',
							'windows\\helpers\\notifier\\wait_for_gui.ini',
							'windows\\helpers\\notifier\\block_login.ini',
							'windows\\helpers\\notifier\\popup.ini',
							'windows\\helpers\\notifier\\shutdown.ini',
							'windows\\helpers\\notifier\\event.bmp',
							'windows\\helpers\\notifier\\action.bmp',
							'windows\\helpers\\notifier\\userlogin.bmp',
							'windows\\helpers\\notifier\\wait_for_gui.bmp',
							'windows\\helpers\\notifier\\block_login.bmp',
							'windows\\helpers\\notifier\\popup.bmp',
							'windows\\opsi.ico' ]),
		('opsiclientd',                   [	'windows\\opsiclientd.conf']),
		('locale\\de\\LC_MESSAGES',       [     '..\\gettext\\opsiclientd_de.mo']),
		('locale\\fr\\LC_MESSAGES',       [     '..\\gettext\\opsiclientd_fr.mo']),
		('locale\\es\\LC_MESSAGES',       [     '..\\gettext\\opsiclientd_es.mo']),
		('locale\\it\\LC_MESSAGES',       [     '..\\gettext\\opsiclientd_it.mo']),
		('locale\\da\\LC_MESSAGES',       [     '..\\gettext\\opsiclientd_da.mo']),
		('opsiclientd\\extend.d', glob.glob('..\\extend.d\*.*')),
	]
else:
	data_files = []
data_files += tree('opsiclientd\\static_html', '..\\static_html')

setup_options = {
	"data_files": data_files,
	"name": "opsiclientd",
	"description": (
		'opsiclientd is part of the desktop management solution opsi (open pc '
		'server integration) - http://www.opsi.org'
	),
	"version": opsiClientDeamonVersion,
	"url": 'http://www.opsi.org/',
	"author": "uib GmbH <info@uib.de>",
	"author_email": "info@uib.de",
	"license": "GNU Affero General Public License Version 3 (AGPLv3)",
    "install_requires": [
        "python-opsi >= 4.1.1.36, <= 4.2",
        "cryptography",
    ],
    "extras_require": {
        'test': ['pytest >= 3.0', 'mock'],
        'qa': ['pytest-cov >= 2.3.1', 'pylint', 'flake8']
    },
}

if RUNS_ON_WINDOWS:
	manifest_template = '''
<?xml version="1.0" encoding="utf-8"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <trustInfo xmlns="urn:schemas-microsoft-com:asm.v3">
    <security>
      <requestedPrivileges>
        <requestedExecutionLevel level="highestAvailable" />
      </requestedPrivileges>
    </security>
  </trustInfo>
  <assemblyIdentity
     version="5.0.0.0"
     processorArchitecture="x86"
     name="%(prog)s"
     type="win32"
  />
  <description>%(prog)s Program</description>
  <dependency>
     <dependentAssembly>
         <assemblyIdentity
             type="win32"
             name="Microsoft.Windows.Common-Controls"
             version="6.0.0.0"
             processorArchitecture="X86"
             publicKeyToken="6595b64144ccf1df"
             language="*"
         />
     </dependentAssembly>
 </dependency>
   <compatibility xmlns="urn:schemas-microsoft-com:compatibility.v1">
        <application>
            <!-- Windows 8.1 -->
            <supportedOS Id="{1f676c76-80e1-4239-95bb-83d0f6d0da78}"/>
            <!-- Windows Vista -->
            <supportedOS Id="{e2011457-1546-43c5-a5fe-008deee3d3f0}"/>
            <!-- Windows 7 -->
            <supportedOS Id="{35138b9a-5d96-4fbd-8e2d-a2440225f93a}"/>
            <!-- Windows 8 -->
            <supportedOS Id="{4a2f28e3-53b9-4441-ba9c-d69d4a4a6e38}"/>
        </application>
    </compatibility>
</assembly>
'''

	RT_MANIFEST = 24

	opsiclientd = Target(
		name="opsiclientd",
		description=opsiclientdDescription,
		script="scripts/opsiclientd",
		modules=['ocdlib.Windows'],
		#cmdline_style='pywin32',
		#other_resources = [(RT_MANIFEST, 1, manifest_template % dict(prog="opsiclientd"))],
		icon_resources=[(1, "windows\\opsi.ico")]
	)

	notifier = Target(
		name = "notifier",
		description = "opsi notifier",
		script = "windows\\helpers\\notifier\\notifier.py",
		# other_resources = [(RT_MANIFEST, 1, manifest_template % dict(prog="notifier"))],
		icon_resources = [(1, "windows\\opsi.ico")]
	)

	opsiclientd_rpc = Target(
		name = "opsiclientd_rpc",
		description = "opsi client daemon rpc tool",
		script = "windows\\helpers\\opsiclientd_rpc\\opsiclientd_rpc.py",
		icon_resources = [(1, "windows\\opsi.ico")]
	)

	action_processor_starter = Target(
		name = "action_processor_starter",
		description = "opsi action processor starter",
		script = "windows\\helpers\\action_processor_starter\\action_processor_starter.py",
		icon_resources = [(1, "windows\\opsi.ico")]
	)

	network_performance = Target(
		name = "network_performance",
		description = "network performance",
		script = "tests\\network_performance.py",
		icon_resources = [(1, "windows\\opsi.ico")]
	)

	opsiclientd_shutdown_starter = Target(
		name = "opsiclientd_shutdown_starter",
		description = "opsi client daemon shutdown-starter tool",
		script = "windows\\helpers\\opsiclientd_shutdown_starter\\opsiclientd_shutdown_starter.py",
		icon_resources = [(1, "windows\\opsi.ico")]
	)

	# These are options required by py2exe
	setup_options['options'] = {
		"py2exe": {
			"compressed": 1,
			"optimize": 2,
			"excludes": excludes,
                        "includes": includes,
			"packages": packages + ["OPSI", "twisted"]
		}
	}

	setup_options['zipfile'] = "lib/library.zip"
	setup_options['service'] = [opsiclientd]
	setup_options['console'] = [network_performance, opsiclientd_shutdown_starter]
	setup_options['windows'] = [notifier, opsiclientd_rpc, 	action_processor_starter]
else:
	setup_options['scripts'] = [os.path.join('scripts', 'opsiclientd')]
	setup_options['packages'] = packages

setup(**setup_options)

if os.path.exists(os.path.join("dist", "locale")):
	for lang in os.listdir(os.path.join("dist", "locale")):
		dn = os.path.join("dist", "locale", lang, "LC_MESSAGES")
		for mo in os.listdir(dn):
			src = os.path.join(dn, mo)
			if mo.endswith('_%s.mo' % lang):
				dst = os.path.join(dn, mo.split('_%s.mo' % lang)[0] + '.mo')
				os.rename(src, dst)

if RUNS_ON_WINDOWS:
	os.unlink(os.path.join("dist", "w9xpopen.exe"))

	print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
	print "!!!   On the target machine always replace exe AND lib   !!!"
	print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
