# SPDX-License-Identifier: MIT
{ lib }:
path: type:
let
  name = baseNameOf path;
in
!(builtins.elem name [
  ".git"
  ".terraform"
  ".tofu-purifier"
  "__pycache__"
])
&& !(lib.hasPrefix "result" name)
&& !(lib.hasInfix ".tfstate" name)
&& !(lib.hasSuffix ".tfplan" name)
&& !(lib.hasSuffix ".tfvars" name)
&& !(lib.hasSuffix ".tfvars.json" name)
