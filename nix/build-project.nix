# SPDX-License-Identifier: MIT
{
  lib,
  stdenv,
  runCommand,
  fetchurl,
  fetchgit,
  unzip,
  zstd,
  python3,
  nativeTool,
  gnutar,
  gzip,
  purifier,
}:
{
  src,
  lockFile ? src + "/tofu-purifier.lock.json",
  tofuLock ? src + "/.terraform.lock.hcl",
  fetchers ? { },
  srcFilter ? import ./source-filter.nix { inherit lib; },
  testCommand ? "tofu test -no-color",
}:
let
  lock = purifier.checkLock (
    (import ./read-lock.nix { inherit lib; }) { inherit src lockFile tofuLock; }
  );
  dependencies =
    (import ./dependencies.nix {
      inherit
        lib
        stdenv
        runCommand
        fetchurl
        fetchgit
        unzip
        zstd
        purifier
        ;
    })
      { inherit lock fetchers; };
  source = lib.cleanSourceWith {
    inherit src;
    filter = srcFilter;
  };
  python = python3.withPackages (p: [ p.python-hcl2 ]);
  configuration =
    runCommand "tofu-configuration"
      {
        nativeBuildInputs = [
          nativeTool
          python
        ];
      }
      ''
        export HOME="$TMPDIR/home" TF_IN_AUTOMATION=1 TF_DATA_DIR="$out/.terraform"
        export NIX_PURIFIER_NATIVE_LOCKFILE="$out/.terraform.lock.hcl"
        mkdir -p "$HOME" "$out"
        cp -r ${source}/. "$out/"
        chmod -R u+w "$out"
        cp ${tofuLock} "$out/.terraform.lock.hcl"
        cp ${lockFile} "$out/tofu-purifier.lock.json"
        python ${../tofu_purifier/materialize.py} "$out" ${lockFile} ${dependencies}
        tofu -chdir="$out" init -backend=false -get=false -input=false -lockfile=readonly -no-color ${
          lib.optionalString (lock.providerVersions != { }) "-plugin-dir=${dependencies}/providers"
        }
        tofu -chdir="$out" validate -no-color
      '';
  tests = runCommand "tofu-project-tests" { nativeBuildInputs = [ nativeTool ]; } ''
    export HOME="$TMPDIR/home" TF_IN_AUTOMATION=1
    mkdir -p "$HOME"
    cp -r ${configuration} work
    chmod -R u+w work
    cd work
    export TF_DATA_DIR="$PWD/.terraform" NIX_PURIFIER_NATIVE_LOCKFILE="$PWD/.terraform.lock.hcl"
    ${testCommand}
    touch "$out"
  '';
  release =
    runCommand "tofu-release"
      {
        nativeBuildInputs = [
          gnutar
          gzip
        ];
      }
      ''
        test -e ${tests}
        mkdir -p "$out" work
        cp -r ${source}/. work/
        chmod -R u+w work
        cp ${tofuLock} work/.terraform.lock.hcl
        cp ${lockFile} work/tofu-purifier.lock.json
        tar --sort=name --mtime=@1 --owner=0 --group=0 --numeric-owner -C work -cf - . | gzip -n > "$out/source.tar.gz"
      '';
in
assert
  lock.toolVersion == nativeTool.version
  || throw "tofu-purifier: lock needs OpenTofu ${lock.toolVersion}; override the scope's nativeTool or regenerate the lock";
{
  packages.configuration = configuration;
  inherit tests release dependencies;
  fetches = lock.entries;
}
