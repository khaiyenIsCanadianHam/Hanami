#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -r requirements-dev.txt
.venv/bin/flask --app run:create_app db upgrade
.venv/bin/flask --app run:create_app seed-templates
printf '%s\n' 'Setup complete. Create your own administrator with: .venv/bin/flask --app run:create_app create-admin'
