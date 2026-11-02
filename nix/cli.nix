# SPDX-License-Identifier: MIT
{
  lib,
  stdenvNoCC,
  makeWrapper,
  python3,
  git,
  nix,
  nativeTool,
  tofu-ls,
  nix-prefetch-git,
  gh,
  cacert,
  nixpkgsSrc,
  purifierSrc,
}:
stdenvNoCC.mkDerivation {
  pname = "tofu-purifier";
  version = "0.1.0";
  src = ../.;
  nativeBuildInputs = [ makeWrapper ];
  dontBuild = true;
  installPhase = ''
    mkdir -p "$out/bin" "$out/lib/tofu-purifier"
    cp -r tofu_purifier nix "$out/lib/tofu-purifier/"
    install -m755 bin/tofu-purifier "$out/bin/tofu-purifier"
    substituteInPlace "$out/lib/tofu-purifier/nix/realize.nix" \
      --replace-fail '@nixpkgs@' '${nixpkgsSrc}' \
      --replace-fail '@purifier@' '${purifierSrc}' \
      --replace-fail '@runtime@' "$out"
    wrapProgram "$out/bin/tofu-purifier" \
      --prefix PATH : ${
        lib.makeBinPath [
          (python3.withPackages (p: [ p.python-hcl2 ]))
          git
          nix
          nativeTool
          nix-prefetch-git
          gh
        ]
      } \
      --prefix PYTHONPATH : "$out/lib/tofu-purifier" \
      --set TOFU_PURIFIER_TOOL ${nativeTool}/bin/tofu \
      --set TOFU_PURIFIER_REALIZE "$out/lib/tofu-purifier/nix/realize.nix" \
      --set-default SSL_CERT_FILE ${cacert}/etc/ssl/certs/ca-bundle.crt
    makeWrapper "$out/bin/tofu-purifier" "$out/bin/tofu" --add-flags "native --"
    ln -s ${tofu-ls}/bin/tofu-ls "$out/bin/tofu-ls"
  '';
  meta = {
    description = "Locked, Nix-resolved OpenTofu dependencies";
    license = lib.licenses.mit;
    platforms = lib.platforms.linux;
    mainProgram = "tofu-purifier";
    homepage = "https://nix-purifiers.github.io/";
  };
}
