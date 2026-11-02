# SPDX-License-Identifier: MIT
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import hcl2
from lark.exceptions import LarkError
ADVICE='run tofu-purifier lock (use --lockfile and --tofu-lock for external locks)'
def canonical(value):return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'))
def digest(value):return hashlib.sha256(canonical(value).encode()).hexdigest()
def file_hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def seal(data):
    data={k:v for k,v in data.items() if k!='contentHash'}
    return {**data,'contentHash':digest(data)}
def providers(path):
    try:
        with Path(path).open() as stream:data=hcl2.load(stream)
    except LarkError as error:raise ValueError("cannot parse native lock; "+ADVICE) from error
    result={}
    for record in data.get('provider',[]):
        for name,value in record.items():
            if name in result:raise ValueError('duplicate provider addresses')
            result[name]=value
    return result

def configuration(root,modules=None):
    root=Path(root);result={}
    directories=['']+[m['dir'] for m in (modules or {}).values() if m['kind']=='local']
    directories+= [str(Path(directory)/'tests') for directory in list(directories) if (root/directory/'tests').is_dir()]
    for directory in directories:
        for path in sorted((root/directory).iterdir()):
            if path.name.endswith(('.tf','.tf.json','.tofu','.tofu.json','.tftest.hcl','.tofutest.hcl')):
                if not path.resolve().is_relative_to(root.resolve()):raise ValueError('configuration file escapes the source')
                result[str(path.relative_to(root))]=file_hash(path)
    return result

def safe_path(value,empty=False):
    return isinstance(value,str) and ((empty and value in ('','.')) or (bool(value) and not value.startswith('/') and '..' not in Path(value).parts and re.fullmatch('[A-Za-z0-9_.+/-]+',value) is not None))

def http_url(value):
    if not isinstance(value,str):return False
    p=urlsplit(value);return p.scheme in ('http','https') and bool(p.hostname) and not p.username and not p.password and not p.fragment

def problems(root,native,data):
    try:
        if not isinstance(data,dict) or data.get('version')!=1:raise ValueError('unsupported companion lock format')
        if data.get('contentHash')!=seal(data)['contentHash']:raise ValueError('contentHash mismatch')
        if not isinstance(data.get('toolVersion'),str) or not isinstance(data.get('providers'),dict) or not isinstance(data.get('modules'),dict) or not isinstance(data.get('moduleKeys'),list):raise ValueError('missing provider/module metadata')
        native_providers=providers(native)
        if set(native_providers)!=set(data['providers']):raise ValueError('missing provider download entries')
        for address,provider in native_providers.items():
            parts=address.split('/')
            if len(parts)!=3 or not all(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_.:-]*',p) and '..' not in p for p in parts):raise ValueError('invalid provider address')
            if not re.fullmatch('[0-9][A-Za-z0-9.+-]*',provider['version']) or not isinstance(provider['hashes'],list):raise ValueError('invalid native provider version/hashes')
            platforms=data['providers'][address]
            if not isinstance(platforms,dict) or not platforms:raise ValueError('missing provider platforms')
            for platform,download in platforms.items():
                if platform not in ['linux_amd64','linux_arm64']:raise ValueError('unsupported provider platform')
                if not http_url(download['url']):raise ValueError('invalid provider archive URL')
                index=download['hashIndex']
                if type(index) is not int or index<0 or index>=len(provider['hashes']) or not re.fullmatch('zh:[0-9a-f]{64}',provider['hashes'][index]):raise ValueError('missing native zip hash selection')
        if sorted(data['modules'])!=sorted(data['moduleKeys']) or len(set(data['moduleKeys']))!=len(data['moduleKeys']):raise ValueError('missing module entries')
        for key,module in data['modules'].items():
            if not re.fullmatch(r'[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*',key):raise ValueError('invalid module key')
            if not isinstance(module.get('source'),str):raise ValueError('missing module source')
            if module['kind']=='git':
                if not isinstance(module.get('url'),str) or not re.fullmatch('[0-9a-f]{40}',module.get('rev','')) or not re.fullmatch('sha256-[A-Za-z0-9+/]{43}=',module.get('hash','')) or not safe_path(module.get('subdir'),True):raise ValueError('invalid Git module pin')
            elif module['kind']=='local':
                if not safe_path(module.get('dir')) or not (Path(root)/module['dir']).is_dir():raise ValueError('invalid local module directory')
            else:raise ValueError('unsupported module source')
        if data.get('inputs',{}).get('native')!=file_hash(native) or data.get('inputs',{}).get('configuration')!=configuration(root,data['modules']):raise ValueError('configuration or native lock changed after locking')
        return []
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as error:return [f'tofu-purifier: {error}; {ADVICE}']
