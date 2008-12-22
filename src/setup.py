from distutils.core import setup
import py2exe, sys, os, shutil
 
VC_90_INST_DIR = 'C:\\WINDOWS\\WinSxS\\x86_Microsoft.VC90.CRT_1fc8b3b9a1e18e3b_9.0.21022.8_x-ww_d08d0375'
SYS_DIR = 'c:\\windows\\system32'

for dll in ('msvcm90.dll'):#, 'msvcp90.dll', 'msvcr90.dll'):
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

opsiclientd = Target(
	name = "opsiclientd",
	description = "opsi client daemon",
	script = "opsiclientd.py",
	modules = ["opsiclientd"],
	version = "0.2.6.8"
)

status_window = Target(
	name = "status_window",
	description = "opsi status window",
	script = "windows\\helpers\\status_window\\status_window.py",
	version = "0.2.3"
)

opsiclientd_rpc = Target(
	name = "opsiclientd_rpc",
	description = "opsi client daemon rpc tool",
	script = "windows\\helpers\\opsiclientd_rpc\\opsiclientd_rpc.py",
	version = "0.1"
)

################################################################
# COM pulls in a lot of stuff which we don't want or need.

excludes = [	"pywin", "pywin.debugger", "pywin.debugger.dbgcon",
		"pywin.dialogs", "pywin.dialogs.list",
		"Tkconstants", "Tkinter", "tcl", "_imagingtk",
		"PIL._imagingtk", "ImageTk", "PIL.ImageTk", "FixTk"
]

data_files = [
	('lib',                      ['C:\\Programme\\python25\\lib\\site-packages\\Pythonwin\\MFC71.DLL',
	                              SYS_DIR + '\\msvcm90.dll'])
	('status_windows',           ['windows\\helpers\\status_window\\skin.ini', 'windows\\helpers\\status_window\\bg.bmp']),
	('opsiclientd',              ['windows\\opsiclientd.conf']),
	('opsiclientd\\static_html', ['..\\static_html\\favicon.ico', 'static_html\\index.html', 'static_html\\opsi_logo.png'])
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
	windows = [ status_window ],
	console = [ opsiclientd_rpc ],
)

