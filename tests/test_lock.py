# SPDX-License-Identifier: MIT
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from tofu_purifier import lock
SOURCE=Path(__file__).resolve().parents[1]
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        shutil.copytree(SOURCE/'examples/random',self.root,dirs_exist_ok=True,ignore=shutil.ignore_patterns('.terraform','.tofu-purifier'))
        self.native=self.root/'.terraform.lock.hcl';self.path=self.root/'tofu-purifier.lock.json';self.data=json.loads(self.path.read_text())
    def problems(self):return lock.problems(self.root,self.native,self.data)
    def test_valid(self):self.assertEqual(self.problems(),[])
    def test_stale(self):
        with (self.root/'main.tf').open('a') as stream:stream.write('\n')
        self.assertTrue(self.problems())
    def test_tampered(self):
        self.data['providers']={};self.assertTrue(self.problems())
    def test_missing_provider(self):
        self.data['providers']={};self.data=lock.seal(self.data);self.assertTrue(self.problems())
    def test_missing_module(self):
        self.data['modules']={};self.data=lock.seal(self.data);self.assertTrue(self.problems())
    def test_bad_hash_index(self):
        for target in next(iter(self.data['providers'].values())).values():target['hashIndex']=-1
        self.data=lock.seal(self.data);self.assertTrue(self.problems())
    def test_module_traversal(self):
        next(iter(self.data['modules'].values()))['subdir']='../../outside';self.data=lock.seal(self.data);self.assertTrue(self.problems())
    def test_malformed_native(self):
        self.native.write_text('provider "unterminated');self.assertTrue(self.problems())
    def test_state_does_not_affect_lock(self):
        (self.root/'terraform.tfstate').write_text('STATE');self.assertEqual(self.problems(),[])
    def test_missing_lock_delegates_arguments_streams_and_status(self):
        self.path.unlink();tool=self.root/'tool';tool.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nprintf "native stderr\\n" >&2\nexit 23\n');tool.chmod(0o755)
        result=subprocess.run([sys.executable,'-m','tofu_purifier.cli','native','--','validate','-no-color'],cwd=self.root,env={**os.environ,'PYTHONPATH':str(SOURCE),'TOFU_PURIFIER_TOOL':str(tool)},capture_output=True,text=True)
        self.assertEqual(result.returncode,23);self.assertEqual(result.stdout,'validate\n-no-color\n');self.assertIn('warning: no lockfile',result.stderr);self.assertIn('native stderr',result.stderr)
    def test_invalid_lock_never_delegates(self):
        self.path.write_text('{}')
        result=subprocess.run([sys.executable,'-m','tofu_purifier.cli','native','--','validate'],cwd=self.root,env={**os.environ,'PYTHONPATH':str(SOURCE),'TOFU_PURIFIER_TOOL':'/not/a/tool'},capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0);self.assertIn('unsupported companion lock format',result.stderr);self.assertNotIn('warning: no lockfile',result.stderr)
