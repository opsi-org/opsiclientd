from distutils.core import setup
import py2exe, sys, os, shutil, glob

for d in ('build', 'dist'):
	if os.path.exists(d):
		shutil.rmtree(d)

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
		f = open(os.path.join('ocdlib', 'Opsiclientd.py'), 'r')
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
	#cmdline_style='pywin32',
)

# manifest_template = '''
# <?xml version="1.0" encoding="UTF-8" standalone="yes"?>
# <assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
# <assemblyIdentity
#     version="5.0.0.0"
#     processorArchitecture="x86"
#     name="%(prog)s"
#     type="win32"
# />
# <description>%(prog)s Program</description>
# <dependency>
#     <dependentAssembly>
#         <assemblyIdentity
#             type="win32"
#             name="Microsoft.Windows.Common-Controls"
#             version="6.0.0.0"
#             processorArchitecture="X86"
#             publicKeyToken="6595b64144ccf1df"
#             language="*"
#         />
#     </dependentAssembly>
# </dependency>
# </assembly>
# '''
# 
# RT_MANIFEST = 24

notifier = Target(
	name = "notifier",
	description = "opsi notifier",
	script = "windows\\helpers\\notifier\\notifier.py",
	# other_resources = [(RT_MANIFEST, 1, manifest_template % dict(prog="notifier"))],
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
	('Microsoft.VC90.MFC', glob.glob('Microsoft.VC90.MFC\*.*')),
	('Microsoft.VC90.CRT', glob.glob('Microsoft.VC90.CRT\*.*')),
	('lib\\Microsoft.VC90.MFC', glob.glob('Microsoft.VC90.MFC\*.*')),
	('lib\\Microsoft.VC90.CRT', glob.glob('Microsoft.VC90.CRT\*.*')),
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
						'windows\\helpers\\notifier\\opsi.ico' ]),
	('opsiclientd',                   [	'windows\\opsiclientd.conf']),
	('opsiclientd\\static_html',      [	'..\\static_html\\favicon.ico', '..\\static_html\\index.html', '..\\static_html\\opsi_logo.png']),
	('opsiclientd\\backendManager.d', [	'..\\cache_service.conf']),
	('opsiclientd\\locale\\de\\LC_MESSAGES\\opsiclientd.mo', ['..\\gettext\\opsiclientd_de.mo'),
]
#data_files += tree("static_html")

setup(
	options = {
		"py2exe": {
			"compressed": 1,
			#"bundle_files": 1,
			"optimize": 2,
			"excludes": excludes,
			"packages": ["OPSI", "twisted", "ocdlib"]
		}
	},
	data_files = data_files,
	zipfile = "lib/library.zip",
	service = [ opsiclientd ],
	windows = [ notifier, opsiclientd_rpc, action_processor_starter ],
)

os.unlink(os.path.join("dist", "w9xpopen.exe"))

print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
print "!!!   On the target machine always replace exe AND lib   !!!"
print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"

