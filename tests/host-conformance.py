# SPDX-License-Identifier: MIT
"""Check real native Git module updates, external locks and offline use."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import time

SOURCE=Path(__file__).resolve().parents[1]
case=sys.argv[1]
def run(args,**kwargs):
    result=subprocess.run(list(map(str,args)),text=True,**kwargs)
    if result.returncode:
        if result.stderr:print(result.stderr,file=sys.stderr)
        result.check_returncode()
    return result
with tempfile.TemporaryDirectory(prefix='tofu-conformance-') as temporary:
    temp=Path(temporary);run(['nix','build',SOURCE,'--out-link',temp/'cli'])
    cli=temp/'cli/bin/tofu-purifier';tool=temp/'cli/bin/tofu'
    root=temp/'project';root.mkdir();native=temp/'locks/provider.hcl' if case=='external' else root/'.terraform.lock.hcl'
    sidecar=temp/'locks/tofu.json' if case=='external' else root/'tofu-purifier.lock.json'
    daemon=None
    def purifier(*args):return run([cli,'--project',root,'--tofu-lock',native,'--lockfile',sidecar,*args])
    if case=='external':
        shutil.copytree(SOURCE/'examples/random',root,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.terraform','.tofu-purifier','tofu-purifier.lock.json'))
        native.parent.mkdir();shutil.copyfile(root/'.terraform.lock.hcl',native)
        (root/'.terraform.lock.hcl').write_text('# Working copy is deliberately not the selected provider lock.\n')
        source_native=(root/'.terraform.lock.hcl').read_bytes();purifier('lock')
    else:
        work=temp/'module';work.mkdir();(work/'child').mkdir()
        run(['git','init','-b','main',work]);run(['git','-C',work,'config','user.email','purifier-tests@example.invalid']);run(['git','-C',work,'config','user.name','Purifier tests'])
        (work/'main.tf').write_text('module "child" { source = "./child" }\noutput "value" { value = module.child.value }\n')
        def commit(value):
            (work/'child/main.tf').write_text(f'output "value" {{ value = "{value}" }}\n')
            run(['git','-C',work,'add','.']);run(['git','-C',work,'commit','-m',value])
            if (temp/'git/module.git').exists():run(['git','-C',work,'push',temp/'git/module.git','main'])
            return run(['git','-C',work,'rev-parse','HEAD'],capture_output=True).stdout.strip()
        first=commit('one');(temp/'git').mkdir();run(['git','clone','--bare',work,temp/'git/module.git'])
        with socket.socket() as connection:connection.bind(('127.0.0.1',0));port=connection.getsockname()[1]
        daemon=subprocess.Popen(['git','daemon','--reuseaddr','--export-all','--listen=127.0.0.1',f'--port={port}',f'--base-path={temp}/git'],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1',port),timeout=.1):break
            except OSError:time.sleep(.02)
        (root/'main.tf').write_text(f'module "example" {{ source = "git::git://127.0.0.1:{port}/module.git?ref=main" }}\noutput "value" {{ value = module.example.value }}\nvariable "expected" {{ default = "one" }}\n')
        (root/'tests').mkdir()
        def test(value):(root/'tests/check.tftest.hcl').write_text(f'run "module" {{\n command = plan\n assert {{\n condition = output.value == var.expected\n error_message = "Wrong locked Git module."\n }}\n}}\n')
        test('one');native.write_text('# Selected empty provider lock.\n');purifier('lock')
    try:
        original=sidecar.read_bytes();old_native=native.read_bytes()
        if case=='relock':
            purifier('lock');assert sidecar.read_bytes()==original and native.read_bytes()==old_native
            sidecar.write_text('{broken');purifier('lock');assert sidecar.read_bytes()==original and native.read_bytes()==old_native
            commit('two')
            with (root/'main.tf').open('a') as stream:stream.write('\n')
            purifier('lock')
            retained=json.loads(sidecar.read_text());assert all(m['rev']==first for m in retained['modules'].values()),retained
        elif case=='update':
            second=commit('two');purifier('lock');assert sidecar.read_bytes()==original
            purifier('update');updated=json.loads(sidecar.read_text());assert all(m['rev']==second for m in updated['modules'].values()),updated
            # The test input changes, while its dependency declarations stay fixed.
        elif case!='external':raise ValueError(case)
        purifier('prefetch')
        if daemon is not None:daemon.terminate();daemon.wait(timeout=10);daemon=None
        env={**os.environ,'TF_VAR_expected':'two' if case=='update' else 'one','TOFU_PURIFIER_TOFU_LOCK':str(native),'TOFU_PURIFIER_LOCKFILE':str(sidecar)}
        run([tool,'init','-backend=false','-input=false','-no-color'],cwd=root,env=env)
        run([tool,'validate','-no-color'],cwd=root,env=env)
        run([tool,'test','-no-color'],cwd=root,env=env)
        assert not list(root.glob('*.nix'))
        if case=='external':
            assert (root/'.terraform.lock.hcl').read_bytes()==source_native
            assert native.read_bytes()==old_native and sidecar.read_bytes()==original
            (root/'terraform.tfstate').write_text('STATE MUST NOT ENTER THE RELEASE')
            (root/'private.tfvars').write_text('VARIABLE INPUTS MUST NOT ENTER THE RELEASE')
            run(['nix','build','--impure','--file',temp/'cli/lib/tofu-purifier/nix/realize.nix','--argstr','project',root,'--argstr','lockFile',sidecar,'--argstr','tofuLock',native,'--argstr','target','release','--out-link',temp/'release'])
            with tarfile.open(temp/'release/source.tar.gz') as archive:assert all('.tfstate' not in name and not name.endswith('.tfvars') for name in archive.getnames())
        print(case+': native modules, pinned dependencies and offline plan tests passed')
    finally:
        if daemon is not None:daemon.terminate();daemon.wait(timeout=10)
