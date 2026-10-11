#!/bin/sh
set -eu

exec /usr/bin/python3.12 -m runpod_benchmark.episode1_remote_control "$@"
