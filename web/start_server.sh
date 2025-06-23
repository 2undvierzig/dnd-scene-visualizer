# start_server.sh
#!/usr/bin/env bash
set -Eeuo pipefail

. "$HOME/venvs/fwhisper312/bin/activate"
python main.py

