killall -9 python
poetry run opsiclientd -l5
poetry run pytest -vv tests
