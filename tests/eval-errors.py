# SPDX-License-Identifier: MIT
"""Exercise independent Nix/Python readers on actual malformed input files."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from tofu_purifier import lock

case = sys.argv[1]
source = Path(os.environ['SOURCE'])
lib = os.environ['NIXPKGS_LIB']
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    shutil.copytree(source / 'examples/random', root, dirs_exist_ok=True, copy_function=shutil.copyfile, ignore=shutil.ignore_patterns('.terraform', '.tofu-purifier'))
    path = root / 'tofu-purifier.lock.json'
    data = json.loads(path.read_text())
    if case == 'stale':
        with (root / 'main.tf').open('a') as stream:
            stream.write('\n')
    elif case == 'tampered':
        data['providers'] = {}
        path.write_text(json.dumps(data))
    elif case == 'missing':
        data['providers'] = {}
        path.write_text(json.dumps(lock.seal(data)))
    elif case == 'malformed':
        path.write_text('this is not JSON')
    else:
        raise ValueError(case)
    # The builder must reject the lock before fetching any dependency.
    expr = f'''let
      lib = import {lib};
      read = import {source}/nix/read-lock.nix {{ inherit lib; }};
      checked = (import {os.environ['PURIFIER']}/nix/lib {{ inherit lib; }}).checkLock;
    in checked (read {{ src = builtins.toPath {json.dumps(str(root))}; }})'''
    result = subprocess.run(['nix-instantiate', '--eval', '--strict', '--expr', expr], text=True, capture_output=True)
    assert result.returncode != 0, result.stdout
    assert 'tofu-purifier lock' in result.stderr, result.stderr
    try:
        errors = lock.problems(root, root / '.terraform.lock.hcl', json.loads(path.read_text()))
        assert errors
        assert 'tofu-purifier lock' in errors[0]
    except json.JSONDecodeError:
        assert case == 'malformed'
print(f'{case}: both readers reject unusable locks')
