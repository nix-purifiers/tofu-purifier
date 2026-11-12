# SPDX-License-Identifier: MIT
{ pkgs, self }:
let
  python = pkgs.python3.withPackages (p: [ p.python-hcl2 ]);
  fixture = ../examples/random;
  project = pkgs.tofu-purifier.buildTofuProject { src = fixture; };
  externalSource = builtins.path {
    path = fixture;
    name = "tofu-external-source";
    filter =
      path: type:
      !(builtins.elem (baseNameOf path) [
        ".terraform.lock.hcl"
        "tofu-purifier.lock.json"
        ".terraform"
        ".tofu-purifier"
      ]);
  };
  external = pkgs.tofu-purifier.buildTofuProject {
    src = externalSource;
    lockFile = fixture + "/tofu-purifier.lock.json";
    tofuLock = fixture + "/.terraform.lock.hcl";
  };
  parsed = pkgs.writeText "tofu-native-lock.json" (
    builtins.toJSON (
      import ../lib-overlays/default/provider-lock.nix { inherit (pkgs) lib; } (fixture + "/.terraform.lock.hcl")
    )
  );
  errorCheck =
    case:
    pkgs.runCommand "tofu-${case}"
      {
        nativeBuildInputs = [
          python
          pkgs.nix
        ];
        SOURCE = self;
        NIXPKGS_LIB = "${pkgs.path}/lib";
        PURIFIER = self.inputs.purifier;
        PYTHONPATH = self;
      }
      ''
        export HOME="$TMPDIR/home"
        mkdir -p "$HOME"
        python ${./eval-errors.py} ${case}
        touch "$out"
      '';
in
{
  environment = project.packages.configuration;
  offline = project.tests;
  release = project.release;
  editor =
    pkgs.runCommand "tofu-editor-offline"
      {
        nativeBuildInputs = [
          pkgs.tofu-purifier.nativeTool
          pkgs.tofu-ls
          pkgs.python3
        ];
      }
      ''
        export HOME="$TMPDIR/home"
        mkdir -p "$HOME"
        cp -r ${project.packages.configuration} work
        chmod -R u+w work
        cd work
        export TF_DATA_DIR="$PWD/.terraform" NIX_PURIFIER_NATIVE_LOCKFILE="$PWD/.terraform.lock.hcl"
        python ${./editor.py}
        touch "$out"
      '';
  conformance-external = external.tests;
  unit = pkgs.runCommand "tofu-unit" { nativeBuildInputs = [ python ]; } ''
    cp -r ${self} source
    chmod -R u+w source
    cd source
    python -m unittest discover -s tests -v
    python -c 'import json; from tofu_purifier.lock import providers; assert providers("examples/random/.terraform.lock.hcl") == json.load(open("${parsed}"))'
    touch "$out"
  '';
}
// pkgs.lib.genAttrs [
  "conformance-stale"
  "conformance-tampered"
  "conformance-missing"
  "conformance-malformed"
] (name: errorCheck (pkgs.lib.removePrefix "conformance-" name))
