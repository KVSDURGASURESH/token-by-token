#!/bin/sh
set -eu
exec /usr/bin/python3.12 /opt/episode2/runtime/control.py "$@"
