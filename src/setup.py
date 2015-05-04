# -*- coding: utf-8 -*-

from __future__ import print_function

import glob
import os
import shutil
import sys
from distutils.core import setup


RUNS_ON_WINDOWS = (sys.platform == 'nt')

if RUNS_ON_WINDOWS:
	import py2exe

for directory in ('build', 'dist'):
	if os.path.exists(directory):
		shutil.rmtree(directory)

buildFreeVersion = False
if '--free' in sys.argv:
	buildFreeVersion = True
	sys.argv.remove('--free')

# If run without args, build executables, in quiet mode.
if RUNS_ON_WINDOWS and len(sys.argv) == 1:
	sys.argv.append("py2exe")
	sys.argv.append("-q")

localDirectory = os.path.dirname(__file__)

opsiClientDeamonVersion = None
fileWithVersion = os.path.join(localDirectory, 'ocdlib', '__init__.py')
with open(fileWithVersion, 'r') as f:
	for line in f:
		if "__version__" in line:
			opsiClientDeamonVersion = line.split('=', 1)[1].strip()[1:-1]
			break

if opsiClientDeamonVersion is None:
	raise Exception("Failed to find version.")


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


class Target:
	def __init__(self, **kw):
		self.__dict__.update(kw)
		self.company_name = "uib GmbH"
		self.copyright = "uib GmbH"
		self.version = opsiClientDeamonVersion


opsiclientdDescription = "opsi client daemon"
packages = ["ocdlib"]
excludes = [
	"pywin", "pywin.debugger", "pywin.debugger.dbgcon",	"pywin.dialogs",
	"pywin.dialogs.list", "Tkconstants", "Tkinter", "tcl", "_imagingtk",
	"PIL._imagingtk", "ImageTk", "PIL.ImageTk", "FixTk"
]

if os.path.exists("ocdlibnonfree") and not buildFreeVersion:
	packages.append("ocdlibnonfree")
	opsiclientdDescription = u"opsi client daemon (full)"
else:
	excludes.append("ocdlibnonfree")

print("Building %s (Version %s)" % (opsiclientdDescription, opsiClientDeamonVersion))


def get_locales_target_and_source():
	if RUNS_ON_WINDOWS:
		return [
			(
				os.path.join('locale', 'de', 'LC_MESSAGES'),
				[
					os.path.abspath(os.path.join(localDirectory, 'gettext', 'opsiclientd_de.mo'))
				]
			),
			(
				os.path.join('locale', 'fr', 'LC_MESSAGES'),
				[
					os.path.abspath(os.path.join(localDirectory, 'gettext', 'opsiclientd_fr.mo'))
				]
			),
		]
	else:
		return [
			(
				os.path.join('/etc', 'opsi-client-agent', 'locale'),
				[
					os.path.abspath(os.path.join(localDirectory, 'gettext', 'opsiclientd_de.mo')),
					os.path.abspath(os.path.join(localDirectory, 'gettext', 'opsiclientd_fr.mo'))
				]
			)
		]


data_files = []
data_files += get_locales_target_and_source()

if RUNS_ON_WINDOWS:
	data_files += tree('opsiclientd', 'static_html')
	data_files += [
		('Microsoft.VC90.MFC', glob.glob('Microsoft.VC90.MFC\\*.*')),
		('Microsoft.VC90.CRT', glob.glob('Microsoft.VC90.CRT\\*.*')),
		('lib\\Microsoft.VC90.MFC', glob.glob('Microsoft.VC90.MFC\\*.*')),
		('lib\\Microsoft.VC90.CRT', glob.glob('Microsoft.VC90.CRT\\*.*')),
		('notifier', [
			'windows\\helpers\\notifier\\event.ini',
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
			'windows\\opsi.ico'
			]),
		('opsiclientd', [os.path.join('windows', 'opsiclientd.conf')]),
		(os.path.join('opsiclientd', 'extend.d'), glob.glob(os.path.join('..', 'extend.d', '*.*'))),
	]
else:
	data_files += [
		(
			os.path.join('/etc', 'opsi-client-agent'),
			[os.path.join('linux', 'opsiclientd.conf')]
		),
		(
			os.path.join('/etc', 'opsi-client-agent', 'opsiclientd', 'extend.d'),
			glob.glob(os.path.join('..', 'extend.d', '*.*'))
		),
		(
			os.path.join('/etc', 'opsi-client-agent'),
			[
				os.path.join('linux', 'notifier.py'),
				os.path.join('linux', 'opsiclientd_rpc.py'),
			]
		),
	]
	data_files += tree(os.path.join('/etc', 'opsi-client-agent', 'opsiclientd'), 'static_html')

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
}

if RUNS_ON_WINDOWS:
	opsiclientd = Target(
		name = "opsiclientd",
		description = opsiclientdDescription,
		script = "src\\opsiclientd",
		modules = ["opsiclientd"],
		icon_resources = [(1, "windows\\opsi.ico")]
	)

	notifier = Target(
		name = "notifier",
		description = "opsi notifier",
		script = "windows\\helpers\\notifier\\notifier.py",
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

	# These are options required by py2exe
	setup_options['options'] = {
		"py2exe": {
			"compressed": 1,
			"optimize": 2,
			"excludes": excludes,
			"packages": packages + ["OPSI", "twisted"]
		}
	}

	setup_options['zipfile'] = "lib/library.zip"
	setup_options['service'] = [opsiclientd]
	setup_options['console'] = [network_performance]
	setup_options['windows'] = [notifier, opsiclientd_rpc, 	action_processor_starter]
else:
	setup_options['scripts'] = [os.path.join('scripts', 'opsiclientd')]
	setup_options['packages'] = packages

setup(**setup_options)

locale_path = os.path.join("dist", "locale")
if os.path.exists(locale_path):
	for lang in os.listdir(locale_path):
		dn = os.path.join("dist", "locale", lang, "LC_MESSAGES")
		for mo in os.listdir(dn):
			src = os.path.join(dn, mo)
			if mo.endswith('_%s.mo' % lang):
				dst = os.path.join(dn, mo.split('_%s.mo' % lang)[0] + '.mo')
				os.rename(src, dst)

if RUNS_ON_WINDOWS:
	os.unlink(os.path.join("dist", "w9xpopen.exe"))

	print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
	print("!!!   On the target machine always replace exe AND lib   !!!")
	print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
