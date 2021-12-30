killall -9 python
poetry run pylint --disable=fixme opsiclientd
poetry run pytest -o junit_family=xunit2 --junitxml=testreport.xml --cov-append --cov opsiclientd --cov-report xml -vv tests
poetry run opsiclientd --config-file=tests/data/opsiclientd.conf -l5
poetry run opsiclientd -l5
