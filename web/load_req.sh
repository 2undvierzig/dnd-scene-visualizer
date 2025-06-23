# setup_deps.sh
#!/usr/bin/env bash
set -Eeuo pipefail

VENV="$HOME/venvs/fwhisper312"
. "$VENV/bin/activate"

pip install -U pip wheel setuptools
pip install -r requirements.txt

CUDNN_LIB=$(python - <<'PY'
import pathlib, nvidia.cudnn
print((pathlib.Path(nvidia.cudnn.__file__).parent / "lib"))
PY
)
grep -qxF "export LD_LIBRARY_PATH=$CUDNN_LIB:\$LD_LIBRARY_PATH" "$VENV/bin/activate" || \
	echo "export LD_LIBRARY_PATH=$CUDNN_LIB:\$LD_LIBRARY_PATH" >> "$VENV/bin/activate"

