killall -9 python
uv run ruff format opsiclientd tests
uv run ruff check opsiclientd tests
uv run ty check opsiclientd tests
uv run pytest --tb=short -o junit_family=xunit2 --junitxml=testreport.xml --cov-append --cov opsiclientd --cov-report xml -x -s -vv tests
uv run opsiclientd --config-file=tests/data/opsiclientd.conf -l5
uv run opsiclientd -l5
git push -o ci.skip
opsi-dev-cli git-tag
