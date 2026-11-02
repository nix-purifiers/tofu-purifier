# SPDX-License-Identifier: MIT
"""Connect native provider/module caches to a Nix-built dependency tree."""
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile

def atomic_json(path,data):
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as stream:
        temporary=Path(stream.name);stream.write(json.dumps(data,sort_keys=True)+'\n')
    temporary.replace(path)

def materialize(root,data,dependencies,data_dir=None):
    root=Path(root);dependencies=Path(dependencies);state=Path(data_dir or root/'.terraform');state.mkdir(parents=True,exist_ok=True)
    with (state/'purifier-cache.lock').open('a') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        _materialize(root,data,dependencies,state)

def _materialize(root,data,dependencies,state):
    marker=state/'purifier-cache.json'
    owned=json.loads(marker.read_text()) if marker.exists() else {}
    def link(target,source):
        source=source.resolve();key=str(target)
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.is_symlink() and target.resolve()==source:
            owned[key]=str(source);return
        if target.exists() or target.is_symlink():
            if not (target.is_symlink() and str(target.resolve())==owned.get(key)):
                backup=target.with_name(target.name+'.before-purifier')
                if backup.exists() or backup.is_symlink():raise ValueError(f'cache backup already exists: {backup}')
                target.rename(backup)
        with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as stream:temporary=Path(stream.name)
        temporary.unlink();temporary.symlink_to(source);temporary.replace(target)
        owned[key]=str(source)
    # Parent cache directories stay writable for ordinary native upgrades.
    providers=dependencies/'providers'
    if providers.exists():
        for registry in providers.iterdir():
            for namespace in registry.iterdir():
                for name in namespace.iterdir():
                    for version in name.iterdir():
                        for platform in version.iterdir():
                            target=state/'providers'/registry.name/namespace.name/name.name/version.name/platform.name
                            link(target,platform)
    directory=state/'modules';directory.mkdir(exist_ok=True)
    catalog=[{'Key':'','Source':'','Dir':'.'}]
    for key,module in sorted(data['modules'].items()):
        if module['kind']=='git':
            target=directory/key;link(target,dependencies/'modules'/key)
            path=target/module['subdir']
        else:path=root/module['dir']
        record={'Key':key,'Source':module['source'],'Dir':os.path.relpath(path,root)}
        if module.get('version'):record['Version']=module['version']
        catalog.append(record)
    atomic_json(directory/'modules.json',{'Modules':catalog})
    atomic_json(marker,owned)

if __name__=='__main__':materialize(Path(sys.argv[1]),json.loads(Path(sys.argv[2]).read_text()),Path(sys.argv[3]))
