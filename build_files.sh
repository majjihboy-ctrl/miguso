#!/bin/bash
# Vercel build step. Runs inside @vercel/static-build to prep static assets so
# whitenoise can serve manifest-hashed files from staticfiles/ at request
# time. `python3.12` is the runtime we target, but the build image may only
# expose `python3` — fall back accordingly.
set -e

if command -v python3.12 >/dev/null 2>&1; then
    PY=python3.12
else
    PY=python3
fi

$PY -m pip install --upgrade pip
$PY -m pip install -r requirements.txt
$PY manage.py collectstatic --noinput --clear
