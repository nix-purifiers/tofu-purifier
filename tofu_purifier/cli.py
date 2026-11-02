# SPDX-License-Identifier: MIT
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from . import lock
from .materialize import materialize
import hcl2
from lark.exceptions import LarkError

def tool():return os.environ.get('TOFU_PURIFIER_TOOL','tofu')
def run(arguments,**kwargs):return subprocess.run(list(map(str,arguments)),check=True,**kwargs)
def read(path):
    try:return json.loads(path.read_text())
    except (ValueError,OSError) as error:raise ValueError(f'cannot read {path}: {error}; {lock.ADVICE}') from error
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as stream:
        temporary=Path(stream.name);stream.write(json.dumps(data,sort_keys=True,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)
def ignore(directory,names):
    return [name for name in names if name in ('.git','.terraform','.tofu-purifier','__pycache__') or name.startswith('result') or '.tfstate' in name or name.endswith('.tfplan')]
def native_environment(stage):
    env={**os.environ,'TF_IN_AUTOMATION':'1','TF_DATA_DIR':str(stage/'.terraform'),'NIX_PURIFIER_NATIVE_LOCKFILE':str(stage/'.terraform.lock.hcl')}
    for variable in ['TF_CLI_ARGS','TF_CLI_ARGS_init']:env.pop(variable,None)
    return env

def static_dependencies(directory):
    """Dependency expressions need a variable-input model before support."""
    for path in Path(directory).iterdir():
        if not path.name.endswith(('.tf','.tf.json','.tofu','.tofu.json')):continue
        try:parsed=json.loads(path.read_text()) if path.name.endswith('.json') else hcl2.loads(path.read_text())
        except LarkError as error:raise ValueError(f'cannot inspect HCL dependencies in {path.name}') from error
        modules=parsed.get('module',[])
        if isinstance(modules,dict):modules=[modules]
        for group in modules:
            for module in group.values():
                for field in ['source','version']:
                    if isinstance(module.get(field),str) and ('${' in module[field] or '%{' in module[field]):raise ValueError('computed module sources/version constraints are not supported yet; use literal module coordinates')

def realize(root,native,sidecar,target,out_link):
    run(['nix','build','--impure','--file',os.environ['TOFU_PURIFIER_REALIZE'],'--argstr','project',root,'--argstr','lockFile',sidecar,'--argstr','tofuLock',native,'--argstr','target',target,'--out-link',out_link])
    return out_link.resolve()

def registry_download(address,version,platform,tool_version):
    host,namespace,name=address.split('/')
    scheme='http' if host.startswith(('127.0.0.1:','localhost:')) else 'https'
    origin=f'{scheme}://{host}/'
    headers={'User-Agent':f'OpenTofu/{tool_version} tofu-purifier/0.1.0'}
    def get(url):
        with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=60) as response:return json.load(response)
    discovery=get(origin+'.well-known/terraform.json')
    service=urllib.parse.urljoin(origin,discovery['providers.v1'])
    os_name,architecture=platform.split('_')
    metadata=get(service.rstrip('/')+f'/{namespace}/{name}/{version}/download/{os_name}/{architecture}')
    if metadata.get('os')!=os_name or metadata.get('arch')!=architecture:raise ValueError('registry returned a provider for the wrong platform')
    return {'url':metadata['download_url'],'sha256':metadata['shasum']}

def prefetch_git(url,rev):
    result=run(['nix-prefetch-git','--quiet','--fetch-submodules','--url',url,'--rev',rev],capture_output=True,text=True)
    fetched=json.loads(result.stdout)
    value=fetched.get('hash')
    if value is None:value=run(['nix','hash','convert','--hash-algo','sha256','--to','sri',fetched['sha256']],capture_output=True,text=True).stdout.strip()
    return value,Path(fetched['path'])

def do_lock(root,native,sidecar,update=False,platforms=('linux_amd64','linux_arm64')):
    previous=None
    if sidecar.exists():
        try:
            data=read(sidecar)
            if isinstance(data,dict) and data.get('version')==1 and data.get('contentHash')==lock.seal(data)['contentHash'] and isinstance(data.get('modules'),dict):previous=data
        except ValueError:pass
    if previous and previous.get('platformHashesPrepared') is True and not update and not lock.problems(root,native,previous) and all(set(v)==set(platforms) for v in previous['providers'].values()):
        print(f'Existing dependency resolution retained in {sidecar}');return
    with tempfile.TemporaryDirectory(prefix='tofu-lock-') as temporary:
        stage=Path(temporary)/'source';shutil.copytree(root,stage,ignore=ignore,symlinks=True)
        static_dependencies(stage)
        staged_native=stage/'.terraform.lock.hcl'
        seed=native if native.exists() else root/'.terraform.lock.hcl'
        original=None
        if seed.exists():
            try:
                lock.providers(seed);original=seed.read_bytes();staged_native.write_bytes(original)
            except ValueError:staged_native.unlink(missing_ok=True)
        current_data=Path(os.environ.get('TF_DATA_DIR',root/'.terraform'))
        if not current_data.is_absolute():current_data=root/current_data
        if not update and (current_data/'providers').exists():
            shutil.copytree(current_data/'providers',stage/'.terraform/providers',symlinks=True,dirs_exist_ok=True,ignore=shutil.ignore_patterns('*.before-purifier'))
        old_modules=None
        if previous and not update and any(m.get('kind')=='git' for m in previous['modules'].values()):
            old_modules=realize(root,native,sidecar,'modules',Path(temporary)/'module-pins')
            materialize(stage,previous,old_modules)
        elif not update and (root/'.terraform/modules/modules.json').exists():
            shutil.copytree(root/'.terraform/modules',stage/'.terraform/modules',symlinks=True,dirs_exist_ok=True)
        env=native_environment(stage)
        run([tool(),f'-chdir={stage}','init','-backend=false','-input=false','-no-color',*(['-upgrade'] if update else [])],env=env)
        if not staged_native.exists():staged_native.write_text('# No external providers are required.\n')
        version=run([tool(),'version','-json'],env=env,text=True,capture_output=True)
        tool_version=json.loads(version.stdout)['terraform_version']
        native_providers=lock.providers(staged_native);downloads={};prepared=False
        if previous and previous.get('platformHashesPrepared') is True and seed.exists():
            old_providers=lock.providers(seed)
            prepared=(previous['inputs']['native']==lock.file_hash(seed)
                      and set(old_providers)==set(native_providers)
                      and all(old_providers[a]['version']==p['version'] and old_providers[a]['hashes']==p['hashes'] and set(platforms)<=set(previous['providers'][a]) for a,p in native_providers.items()))
        if prepared:
            downloads={address:{platform:previous['providers'][address][platform] for platform in platforms} for address in native_providers}
        else:
            metadata={address:{platform:registry_download(address,p['version'],platform,tool_version) for platform in platforms} for address,p in native_providers.items()}
            # Unpacked mirrors need native h1 hashes for every target platform,
            # even when the signed lock already contains every archive zh hash.
            if native_providers:
                run([tool(),f'-chdir={stage}','providers','lock',*['-platform='+p for p in platforms]],env=env)
                native_providers=lock.providers(staged_native)
            for address,targets in metadata.items():
                downloads[address]={platform:{'url':download['url'],'hashIndex':native_providers[address]['hashes'].index('zh:'+download['sha256'])} for platform,download in targets.items()}
        catalog=read(stage/'.terraform/modules/modules.json') if (stage/'.terraform/modules/modules.json').exists() else {'Modules':[]}
        modules={};git_hashes={}
        for item in catalog['Modules']:
            key=item['Key']
            if not key:continue
            directory=(stage/item['Dir']).resolve()
            static_dependencies(directory)
            old=(previous or {}).get('modules',{}).get(key)
            if old_modules and old and old.get('kind')=='git' and item['Source']==old['source']:
                same_repository=[k for k,m in previous['modules'].items() if m.get('kind')=='git' and all(m.get(field)==old.get(field) for field in ['url','rev','hash'])]
                if any(directory==(old_modules/'modules'/k/old['subdir']).resolve() for k in same_repository):
                    modules[key]=old;continue
            # Nested Git modules may have their .git in an ancestor.
            probe=subprocess.run(['git','-C',str(directory),'rev-parse','--show-toplevel'],text=True,capture_output=True)
            top=probe if probe.returncode==0 else None
            record={'source':item['Source']}
            if item.get('Version'):record['version']=item['Version']
            if top is not None:
                git_root=Path(top.stdout.strip()).resolve()
                url=run(['git','-C',git_root,'remote','get-url','origin'],text=True,capture_output=True).stdout.strip()
                rev=run(['git','-C',git_root,'rev-parse','HEAD'],text=True,capture_output=True).stdout.strip()
                if (url,rev) not in git_hashes:git_hashes[(url,rev)]=prefetch_git(url,rev)[0]
                nar=git_hashes[(url,rev)]
                subdir=str(directory.relative_to(git_root));subdir='' if subdir=='.' else subdir
                record.update(kind='git',url=url,rev=rev,hash=nar,subdir=subdir)
            elif directory.is_relative_to(stage) and not directory.is_relative_to(stage/'.terraform/modules'):record.update(kind='local',dir=str(directory.relative_to(stage)))
            else:raise ValueError('unsupported non-Git module download; use Git or local module sources')
            modules[key]=record
        if original is not None:
            try:
                if lock.providers(seed)==native_providers:staged_native.write_bytes(original)
            except ValueError:pass
        data=lock.seal({'version':1,'toolVersion':tool_version,'platformHashesPrepared':True,'inputs':{'native':lock.file_hash(staged_native),'configuration':lock.configuration(root,modules)},'providers':downloads,'modules':modules,'moduleKeys':sorted(modules)})
        if errors:=lock.problems(root,staged_native,data):raise ValueError('\n'.join(errors))
        native.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(staged_native,native);write(sidecar,data)
    print(f'Locked {len(downloads)} providers and {len(modules)} modules in {sidecar}')

def prepare(root,native,sidecar):
    data=read(sidecar)
    if errors:=lock.problems(root,native,data):raise ValueError('\n'.join(errors))
    state=sidecar.parent/'.tofu-purifier'/lock.digest(str(root))[:12];state.mkdir(parents=True,exist_ok=True)
    dependencies=realize(root,native,sidecar,'dependencies',state/'dependencies')
    realize(root,native,sidecar,'runtime',state/'runtime')
    data_dir=Path(os.environ.get('TF_DATA_DIR',root/'.terraform'))
    if not data_dir.is_absolute():data_dir=root/data_dir
    materialize(root,data,dependencies,data_dir)
    return dependencies

def root_and_command(arguments):
    root=Path.cwd();index=0
    while index<len(arguments):
        arg=arguments[index]
        if arg.startswith('-chdir='):root=(root/arg.split('=',1)[1]).resolve();index+=1
        elif arg=='-chdir' and index+1<len(arguments):root=(root/arguments[index+1]).resolve();index+=2
        else:break
    return root,index

def main(argv=None):
    parser=argparse.ArgumentParser(prog='tofu-purifier');parser.add_argument('--lockfile');parser.add_argument('--tofu-lock');parser.add_argument('--project')
    sub=parser.add_subparsers(dest='command',required=True)
    create=sub.add_parser('lock');create.add_argument('--platform',action='append')
    update=sub.add_parser('update');update.add_argument('packages',nargs='*');update.add_argument('--platform',action='append')
    sub.add_parser('prefetch')
    wrapper=sub.add_parser('native',help=argparse.SUPPRESS);wrapper.add_argument('args',nargs=argparse.REMAINDER)
    publish=sub.add_parser('publish');publish.add_argument('--repo',required=True);publish.add_argument('--tag',required=True)
    args=parser.parse_args(argv);command=getattr(args,'args',[])
    if command[:1]==['--']:command=command[1:]
    root,index=root_and_command(command)
    if args.project:root=Path(args.project).resolve()
    sidecar=Path(args.lockfile or os.environ.get('TOFU_PURIFIER_LOCKFILE',root/'tofu-purifier.lock.json')).resolve()
    native=Path(args.tofu_lock or os.environ.get('TOFU_PURIFIER_TOFU_LOCK',root/'.terraform.lock.hcl')).resolve()
    try:
        if args.command in ('lock','update'):
            if getattr(args,'packages',[]):raise ValueError('OpenTofu has no native targeted dependency upgrade; update all dependencies or change the selected version constraint and relock')
            do_lock(root,native,sidecar,args.command=='update',getattr(args,'platform',None) or ['linux_amd64','linux_arm64'])
        elif args.command=='prefetch':print(prepare(root,native,sidecar))
        elif args.command=='publish':
            prepare(root,native,sidecar)
            with tempfile.TemporaryDirectory(prefix='tofu-release-') as temp:
                release=realize(root,native,sidecar,'release',Path(temp)/'release')
                run(['gh','release','create',args.tag,release/'source.tar.gz','--repo',args.repo,'--title',args.tag])
        else:
            if not sidecar.exists() and not sidecar.is_symlink():
                os.environ.pop('NIX_PURIFIER_NATIVE_LOCKFILE',None)
                print('tofu-purifier: warning: no lockfile; using ordinary, impure OpenTofu dependency resolution',file=sys.stderr)
                os.execv(tool(),[tool(),*command])
            os.environ['NIX_PURIFIER_NATIVE_LOCKFILE']=str(native)
            action=command[index] if index<len(command) else ''
            if action in ['fmt','version','-version'] or any(a in ('-help','--help','-h') for a in command):os.execv(tool(),[tool(),*command])
            if any(a in ('-upgrade','-upgrade=true','-update','-update=true') for a in command) or command[index:index+2] in (['providers','lock'],['providers','mirror']):raise ValueError('use tofu-purifier lock or update to change locked dependencies')
            if any(a.startswith('-plugin-dir') for a in command):raise ValueError('tofu-purifier supplies the locked plugin directory; use a fetchers override for custom downloads')
            dependencies=prepare(root,native,sidecar)
            os.environ['NIX_PURIFIER_NATIVE_LOCKFILE']=str(native)
            if action=='init':
                command=[*command,'-get=false','-lockfile=readonly']
                if (dependencies/'providers').exists():command.append('-plugin-dir='+str(dependencies/'providers'))
            elif action=='get':command=[*command,'-update=false']
            os.execv(tool(),[tool(),*command])
    except (ValueError,OSError,KeyError,TypeError) as error:print(f'tofu-purifier: {error}',file=sys.stderr);return 1
    except subprocess.CalledProcessError as error:return max(error.returncode,1)
    return 0
if __name__=='__main__':sys.exit(main())
