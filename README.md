# Scripts and tools

## pyinstaller-build.py
This script is used to build executables with pyinstaller.
It should only be used in a docker container (gitlab ci/cd).
The docker container should contain an relatively old os (glibc) for a maximum compatibility of the resulting binaries.
Glibc is backward-compatible, not forward-compatible.

