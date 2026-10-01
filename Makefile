-include .env
export

CACHE := .cache
UTPLSQL_TAG := v.3.2.3
UTPLSQL_SHA256 := ae740a0524f4e6ae0773646d7262e6bd79fa672f41da3b8d3bb80c10917306de
UTPLSQL_CLI_TAG := v3.2.2
UTPLSQL_CLI_SHA256 := 15a3addd921b7f2e415537b47c18a4a9d3e0b70ff0e403943fd4c03b0ba02006
RELEASES := https://github.com/utPLSQL
BRONZE_SCOPE := db/ddl db/init src
PROFILE ?= dev
PYTEST_ARGS ?=
BRONZE_MUTATION := \b(update|delete|merge|truncate)\s+(/\*.*?\*/\s*)?((from|into|table)\s+)?("?\w+"?\.)?"?brz_|\balter\s+table\s+("?\w+"?\.)?"?brz_\w*"?\s+truncate\b|\bgrant\s[^;]*?\b(update|delete|all)\b[^;]*?\bon\s+("?\w+"?\.)?"?brz_

.PHONY: setup up down reset lint bronze-check test access-check e2e

setup: $(CACHE)/utplsql/source/install_headless.sql $(CACHE)/utPLSQL-cli/bin/utplsql
	uv sync --locked

$(CACHE)/utplsql/source/install_headless.sql:
	mkdir -p $(CACHE)/utplsql
	curl -fsSL -o $(CACHE)/utplsql.tar.gz.part $(RELEASES)/utPLSQL/releases/download/$(UTPLSQL_TAG)/utPLSQL.tar.gz
	echo "$(UTPLSQL_SHA256)  $(CACHE)/utplsql.tar.gz.part" | sha256sum --check --quiet
	tar -xzf $(CACHE)/utplsql.tar.gz.part -C $(CACHE)/utplsql --strip-components=1
	rm $(CACHE)/utplsql.tar.gz.part

$(CACHE)/utPLSQL-cli/bin/utplsql:
	mkdir -p $(CACHE)
	curl -fsSL -o $(CACHE)/utplsql-cli.zip.part $(RELEASES)/utPLSQL-cli/releases/download/$(UTPLSQL_CLI_TAG)/utPLSQL-cli.zip
	echo "$(UTPLSQL_CLI_SHA256)  $(CACHE)/utplsql-cli.zip.part" | sha256sum --check --quiet
	unzip -q -o $(CACHE)/utplsql-cli.zip.part -d $(CACHE)
	rm $(CACHE)/utplsql-cli.zip.part

up:
	docker compose up --detach --wait

down:
	docker compose down

reset:
	docker compose down --volumes
	docker compose up --detach --wait

lint: bronze-check
	uv run ruff check src tests
	uv run ruff format --check src tests
	uv run mypy
	uv run sqlfluff lint db

bronze-check:
	grep -rIilPz '$(BRONZE_MUTATION)' $(wildcard $(BRONZE_SCOPE)); test $$? -eq 1

test:
	uv run pytest -m "not perf" $(PYTEST_ARGS)
	@JAVA_OPTS=--enable-native-access=ALL-UNNAMED $(CACHE)/utPLSQL-cli/bin/utplsql run \
		"SRDWH_OWNER/$${SRDWH_OWNER_PASSWORD}@$${SRDWH_DSN}" -f=ut_documentation_reporter -c --failure-exit-code=1

access-check:
	uv run srdwh access-check

e2e: up
	uv run srdwh generate --profile $(PROFILE)
	uv run srdwh run --profile $(PROFILE)
	uv run srdwh access-check
