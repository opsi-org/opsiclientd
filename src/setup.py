from distutils.core import setup
import py2exe, sys, os, shutil
 
VC_90_INST_DIR = 'C:\\WINDOWS\\WinSxS\\x86_Microsoft.VC90.CRT_1fc8b3b9a1e18e3b_9.0.21022.8_x-ww_d08d0375'
SYS_DIR = 'c:\\windows\\system32'

for d in ('build', 'dist'):
	if os.path.exists(d):
		shutil.rmtree(d)
	
for dll in ('msvcm90.dll', 'msvcp90.dll', 'msvcr90.dll'):
	if not os.path.exists(os.path.join(SYS_DIR, dll)):
		shutil.copy2(os.path.join(VC_90_INST_DIR, dll), os.path.join(SYS_DIR, dll))
	if not os.path.exists(os.path.join(VC_90_INST_DIR, dll)):
		print "Failed to locate vc++ dll '%s'" % dll
		sys.exit(1)

# If run without args, build executables, in quiet mode.
if (len(sys.argv) == 1):
	sys.argv.append("py2exe")
	sys.argv.append("-q")

def tree(src):
	list = [(root, map(lambda f: os.path.join(root, f), files)) for (root, dirs, files) in os.walk(os.path.normpath(src))]
	new_list = []
	for (root, files) in list:
		if (len(files) > 0) and (root.count('.svn') == 0):
			new_list.append((root, files))
	return new_list

class Target:
	def __init__(self, **kw):
		self.__dict__.update(kw)
		self.company_name = "uib GmbH"
		self.copyright = "uib GmbH"
		self.version = ""
		f = open(self.script, 'r')
		for line in f.readlines():
			if (line.find("__version__") != -1):
				self.version = line.split('=', 1)[1].strip()[1:-1]
				break
		f.close()
		if not self.version:
			print >> sys.stderr, "Failed to find version of script '%s'" % self.script

opsiclientd = Target(
	name = "opsiclientd",
	description = "opsi client daemon",
	script = "opsiclientd.py",
	modules = ["opsiclientd"],
)

notifier = Target(
	name = "notifier",
	description = "opsi notifier",
	script = "windows\\helpers\\notifier\\notifier.py",
)

opsiclientd_rpc = Target(
	name = "opsiclientd_rpc",
	description = "opsi client daemon rpc tool",
	script = "windows\\helpers\\opsiclientd_rpc\\opsiclientd_rpc.py",
)

action_processor_starter = Target(
	name = "action_processor_starter",
	description = "opsi action processor starter",
	script = "windows\\helpers\\action_processor_starter\\action_processor_starter.py",
)
################################################################
# COM pulls in a lot of stuff which we don't want or need.

excludes = [	"pywin", "pywin.debugger", "pywin.debugger.dbgcon",
		"pywin.dialogs", "pywin.dialogs.list",
		"Tkconstants", "Tkinter", "tcl", "_imagingtk",
		"PIL._imagingtk", "ImageTk", "PIL.ImageTk", "FixTk"
]

data_files = [
	('lib',                           [	'C:\\Programme\\python25\\lib\\site-packages\\Pythonwin\\MFC71.DLL',
						SYS_DIR + '\\msvcm90.dll']),
	('notifier',                      [	'windows\\helpers\\notifier\\event.ini',
						'windows\\helpers\\notifier\\action.ini',
						'windows\\helpers\\notifier\\block.ini',
						'windows\\helpers\\notifier\\action.bmp',
						'windows\\helpers\\notifier\\event.bmp',
						'windows\\helpers\\notifier\\block.bmp',
						'windows\\helpers\\notifier\\opsi.ico']),
	('opsiclientd',                   [	'windows\\opsiclientd.conf']),
	('opsiclientd\\static_html',      [	'..\\static_html\\favicon.ico', '..\\static_html\\index.html', '..\\static_html\\opsi_logo.png']),
	('opsiclientd\\backendManager.d', [	'..\\cache_service.conf'])
]
#data_files += tree("static_html")

setup(
	options = {
		"py2exe": {
			"compressed": 1,
			#"bundle_files": 1,
			"optimize": 2,
			"excludes": excludes,
			"packages": ["OPSI", "twisted"]
		}
	},
	data_files = data_files,
	zipfile = "lib/library.zip",
	service = [ opsiclientd ],
	windows = [ notifier, opsiclientd_rpc, action_processor_starter ],
)

print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
print "!!!   On the target machine always replace exe AND lib   !!!"
print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"

