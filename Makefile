# Thin delegation to tasks.py, which is the single source of truth for
# project commands. `make` is unavailable on Windows, where this project is
# primarily developed, so tasks.py is the canonical entry point:
#
#     python tasks.py <target>
#
# This Makefile exists so Linux, macOS and CI users can keep typing `make`.

PY ?= python

.PHONY: help up down reset ps logs health test lint fmt typecheck check ingest seed eval

help:      ; @$(PY) tasks.py help
up:        ; @$(PY) tasks.py up
down:      ; @$(PY) tasks.py down
reset:     ; @$(PY) tasks.py reset
ps:        ; @$(PY) tasks.py ps
logs:      ; @$(PY) tasks.py logs
health:    ; @$(PY) tasks.py health
test:      ; @$(PY) tasks.py test
lint:      ; @$(PY) tasks.py lint
fmt:       ; @$(PY) tasks.py fmt
typecheck: ; @$(PY) tasks.py typecheck
check:     ; @$(PY) tasks.py check
ingest:    ; @$(PY) tasks.py ingest
seed:      ; @$(PY) tasks.py seed
eval:      ; @$(PY) tasks.py eval
