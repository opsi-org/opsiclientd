#!/usr/bin/python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import glob
import codecs
import shutil
import platform
import subprocess

SCRIPTS = [
	"run-opsiclientd"
]
HIDDEN_IMPORTS = [
]
os.chdir(os.path.dirname(os.path.abspath(__file__)))

subprocess.check_call(["poetry", "install"])

for d in ("dist", "build"):
	if os.path.isdir(d):
		shutil.rmtree(d)

spec_a = ""
spec_m = []
spec_o = ""
for script in SCRIPTS:
	cmd = ["poetry", "run", "pyi-makespec"]
	for hi in HIDDEN_IMPORTS:
		cmd.extend(["--hidden-import", hi])
	cmd.append(script)
	subprocess.check_call(cmd)
	with codecs.open("%s.spec" % script, "r", "utf-8") as f:
		varname = script.replace("-", "_")
		data = f.read()
		data = re.sub(r"([\s\(])a\.", r"\g<1>" + varname + "_a.", data)
		#print(data)
		match = re.search(r"(.*)(a\s*=\s*)(Analysis[^\)]+\))(.*)", data, re.MULTILINE|re.DOTALL)
		if not spec_a:
			spec_a += match.group(1)
		spec_a += "%s_a = %s\n" % (varname, match.group(3))
		spec_o += match.group(4)
		spec_m.append("(%s_a, '%s', '%s')" % (varname, script, script))

with codecs.open("opsiclientd.spec", "w", "utf-8") as f:
	f.write(spec_a)
	f.write("\nMERGE( %s )\n" % ', '.join(spec_m))
	f.write(spec_o)

subprocess.check_call(["poetry", "run", "pyinstaller", "--log-level", "INFO", "opsiclientd.spec"])


shutil.move("dist/%s" % SCRIPTS[0], "dist/opsiclientd")
for script in SCRIPTS[1:]:
	shutil.move("dist/%s/%s" % (script, script), "dist/opsiclientd/%s" % script)
	shutil.rmtree("dist/%s" % script)

