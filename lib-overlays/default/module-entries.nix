# SPDX-License-Identifier: MIT
modules:
builtins.map (
  key:
  let
    m = modules.${key};
  in
  {
    path = "modules/${key}";
    inherit (m) hash;
    git = {
      inherit (m) url rev;
      submodules = true;
      leaveDotGit = false;
      commitObject = null;
    };
  }
) (builtins.filter (key: modules.${key}.kind == "git") (builtins.attrNames modules))
