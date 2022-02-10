![pipeline](https://gitlab.uib.gmbh/uib/opsiclientd/badges/v4.2/pipeline.svg)
![coverage](https://gitlab.uib.gmbh/uib/opsiclientd/badges/v4.2/coverage.svg)

# opsiclientd
This is the service which runs on every windows / linux client managed by [opsi](http://www.opsi.org/).


## License
This library is released under the AGPLv3 and the copyright belongs to
uib GmbH if this is not noted otherwise in the file itself.

# Development in Dev Container
* Install Remote-Containers: https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers
* Open project in container:
	* \<F1\> -> Remote-Containers: Reopen in Container
	* or remote button in bottom left corner -> Reopen in Container
* Run opsiclientd in terminal: `poetry run opsiclientd -l5`

## Run Tests
* Start opsiclientd with test config: `poetry run opsiclientd --config-file=tests/data/opsiclientd.conf`
* Run tests: `poetry run pytest -vv tests`
