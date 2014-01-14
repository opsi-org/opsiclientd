from distutils.core import setup
import py2exe, sys, os, shutil, glob

for d in ('build', 'dist'):
	if os.path.exists(d):
		shutil.rmtree(d)

buildFreeVersion = False
if '--free' in sys.argv:
	buildFreeVersion = True
	sys.argv.remove('--free')

# If run without args, build executables, in quiet mode.
if (len(sys.argv) == 1):
	sys.argv.append("py2exe")
	sys.argv.append("-q")

def tree(dst, src):
	list = []
	for (root, dirs, files) in os.walk(os.path.normpath(src)):
		if '.svn' in (dirs):
			dirs.remove('.svn')
		if root.endswith('.svn'):
			continue
		newfiles = []
		for f in files:
			if f.endswith('~'):
				continue
			newfiles.append(os.path.join(root, f))
		if not newfiles:
			continue
		list.append( (os.path.normpath(os.path.join(dst, root)), newfiles) )
	return list

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

opsiclientdDescription = "opsi client daemon"
packages = ["OPSI", "twisted", "ocdlib"]
excludes = [	"pywin", "pywin.debugger", "pywin.debugger.dbgcon",
		"pywin.dialogs", "pywin.dialogs.list",
		"Tkconstants", "Tkinter", "tcl", "_imagingtk",
		"PIL._imagingtk", "ImageTk", "PIL.ImageTk", "FixTk"
]

if os.path.exists("ocdlibnonfree") and not buildFreeVersion:
	packages.append("ocdlibnonfree")
	opsiclientdDescription = u"opsi client daemon (full)"
else:
	excludes.append("ocdlibnonfree")

print "Building %s" % opsiclientdDescription


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
  <description>%(prog)s Program</description>
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
	name = "opsiclientd",
	description = opsiclientdDescription,
	script = "opsiclientd.py",
	modules = ["opsiclientd"],
	#cmdline_style='pywin32',
	other_resources = [(RT_MANIFEST, 1, manifest_template % dict(prog="opsiclientd"))],
	icon_resources = [(1, "windows\\opsi.ico")]
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

data_files = [
	('Microsoft.VC90.MFC', glob.glob('Microsoft.VC90.MFC\\*.*')),
	('Microsoft.VC90.CRT', glob.glob('Microsoft.VC90.CRT\\*.*')),
	('lib\\Microsoft.VC90.MFC', glob.glob('Microsoft.VC90.MFC\\*.*')),
	('lib\\Microsoft.VC90.CRT', glob.glob('Microsoft.VC90.CRT\\*.*')),
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
	('opsiclientd\\extend.d', glob.glob('..\\extend.d\*.*')),
]
data_files += tree('opsiclientd\\static_html', '..\\static_html')

setup(
	options = {
		"py2exe": {
			"compressed": 1,
			#"bundle_files": 1,
			"optimize": 2,
			"excludes": excludes,
			"packages": packages
		}
	},
	data_files = data_files,
	zipfile = "lib/library.zip",
	service = [ opsiclientd ],
	console = [ network_performance ],
	windows = [ notifier, opsiclientd_rpc, action_processor_starter ],
)
for lang in os.listdir(os.path.join("dist", "locale")):
	dn = os.path.join("dist", "locale", lang, "LC_MESSAGES")
	for mo in os.listdir(dn):
		src = os.path.join(dn, mo)
		if mo.endswith('_%s.mo' % lang):
			dst = os.path.join(dn, mo.split('_%s.mo' % lang)[0] + '.mo')
			os.rename(src, dst)

os.unlink(os.path.join("dist", "w9xpopen.exe"))

print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
print "!!!   On the target machine always replace exe AND lib   !!!"
print "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"

