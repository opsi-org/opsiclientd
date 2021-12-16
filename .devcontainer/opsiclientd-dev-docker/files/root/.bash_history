killall -9 python
poetry run pytest -vv tests
poetry run opsiclientd --config-file=tests/data/opsiclientd.conf -l5
poetry run opsiclientd -l5
