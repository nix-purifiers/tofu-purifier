# SPDX-License-Identifier: MIT
{ lib }:
{
  src,
  lockFile ? src + "/tofu-purifier.lock.json",
  tofuLock ? src + "/.terraform.lock.hcl",
}:
let
  problem =
    message:
    "tofu-purifier: ${message}; run tofu-purifier lock (use --lockfile and --tofu-lock for external locks)";
  exists = builtins.pathExists lockFile && builtins.pathExists tofuLock;
  data =
    if exists then
      builtins.addErrorContext (problem "cannot parse companion lock") (
        builtins.fromJSON (builtins.readFile lockFile)
      )
    else
      { };
  providers = if exists then import ./provider-lock.nix { inherit lib; } tofuLock else { };
  downloads = data.providers or { };
  modules = data.modules or { };
  platforms = {
    linux_amd64 = "x86_64-linux";
    linux_arm64 = "aarch64-linux";
  };
  safePath =
    path:
    builtins.isString path
    && builtins.match "[A-Za-z0-9_.+/-]+" path != null
    && !(lib.hasPrefix "/" path)
    && !(builtins.elem ".." (lib.splitString "/" path));
  baseLocalDirs = [
    ""
  ]
  ++ map (key: modules.${key}.dir) (
    lib.filter (key: modules.${key}.kind == "local") (builtins.attrNames modules)
  );
  localDirs =
    baseLocalDirs
    ++ map (directory: (if directory == "" then "" else directory + "/") + "tests") (
      lib.filter (directory: builtins.pathExists (src + "/${directory}/tests")) baseLocalDirs
    );
  configHashes = lib.foldl' (
    acc: directory:
    let
      path = src + "/${directory}";
      files = if builtins.pathExists path then builtins.readDir path else { };
      names = lib.filter (
        name:
        builtins.any (suffix: lib.hasSuffix suffix name) [
          ".tf"
          ".tf.json"
          ".tofu"
          ".tofu.json"
          ".tftest.hcl"
          ".tofutest.hcl"
        ]
      ) (builtins.attrNames files);
    in
    acc
    // builtins.listToAttrs (
      map (name: {
        name = (if directory == "" then "" else directory + "/") + name;
        value = builtins.hashFile "sha256" (path + "/${name}");
      }) names
    )
  ) { } localDirs;
  urlOK =
    url:
    let
      m = if builtins.isString url then builtins.match "https?://([^/?#]+)([^#]*)" url else null;
    in
    m != null && !(lib.hasInfix "@" (builtins.head m));
  providerOK =
    address:
    let
      p = providers.${address};
      targets = downloads.${address} or { };
      parts = lib.splitString "/" address;
    in
    builtins.length parts == 3
    && builtins.all (
      part: builtins.match "[A-Za-z0-9][A-Za-z0-9_.:-]*" part != null && !(lib.hasInfix ".." part)
    ) parts
    && builtins.isString (p.version or null)
    && builtins.match "[0-9][A-Za-z0-9.+-]*" p.version != null
    && builtins.isList (p.hashes or null)
    && builtins.isAttrs targets
    && targets != { }
    && builtins.all (
      platform:
      let
        d = targets.${platform};
        index = d.hashIndex or null;
      in
      builtins.hasAttr platform platforms
      && builtins.isAttrs d
      && urlOK (d.url or null)
      && builtins.isInt index
      && index >= 0
      && index < builtins.length p.hashes
      && builtins.match "zh:[0-9a-f]{64}" (builtins.elemAt p.hashes index) != null
    ) (builtins.attrNames targets);
  moduleOK =
    key:
    let
      m = modules.${key};
    in
    builtins.match "[A-Za-z0-9_-]+([.][A-Za-z0-9_-]+)*" key != null
    && builtins.isAttrs m
    && builtins.isString (m.source or null)
    && (
      if (m.kind or null) == "git" then
        builtins.isString (m.url or null)
        && builtins.match "[0-9a-f]{40}" (m.rev or "") != null
        && builtins.match "sha256-[A-Za-z0-9+/]{43}=" (m.hash or "") != null
        && ((m.subdir or null) == "" || safePath (m.subdir or null))
      else
        (m.kind or null) == "local" && safePath (m.dir or null) && builtins.pathExists (src + "/${m.dir}")
    );
  problems = map problem (
    if !exists then
      [ "missing companion or native lock" ]
    else if !builtins.isAttrs data || (data.version or null) != 1 then
      [ "unsupported companion lock format" ]
    else if
      (data.contentHash or null)
      != builtins.hashString "sha256" (builtins.toJSON (removeAttrs data [ "contentHash" ]))
    then
      [ "contentHash mismatch" ]
    else if
      !builtins.isAttrs modules
      || !builtins.isAttrs downloads
      || !builtins.isList (data.moduleKeys or null)
      || !builtins.isString (data.toolVersion or null)
    then
      [ "invalid dependency metadata" ]
    else if
      !builtins.all moduleOK (builtins.attrNames modules)
      || builtins.attrNames modules != lib.sort builtins.lessThan data.moduleKeys
      || builtins.length (lib.unique data.moduleKeys) != builtins.length data.moduleKeys
    then
      [ "invalid or missing module entries" ]
    else if
      (data.inputs.native or null) != builtins.hashFile "sha256" tofuLock
      || (data.inputs.configuration or null) != configHashes
    then
      [ "configuration or native lock changed after locking" ]
    else if
      builtins.attrNames providers != builtins.attrNames downloads
      || !builtins.all providerOK (builtins.attrNames providers)
    then
      [ "invalid or missing provider download entries" ]
    else
      [ ]
  );
  providerEntries = lib.concatMap (
    address:
    map (
      platform:
      let
        p = providers.${address};
        d = downloads.${address}.${platform};
        zh = builtins.elemAt p.hashes d.hashIndex;
      in
      {
        path = "providers/${address}/${p.version}/${platform}";
        archive = {
          inherit (d) url;
          mirrors = [ ];
          stripTop = false;
        };
        hash = builtins.convertHash {
          hash = lib.removePrefix "zh:" zh;
          hashAlgo = "sha256";
          toHashFormat = "sri";
        };
        systems = [ platforms.${platform} ];
      }
    ) (builtins.attrNames downloads.${address})
  ) (builtins.attrNames providers);
  usable = problems == [ ];
in
{
  purifier = "tofu-purifier";
  inherit problems;
  outputs.configuration = { };
  entries = if usable then providerEntries ++ import ./module-entries.nix modules else [ ];
  modules = if usable then modules else { };
  providerVersions = if usable then lib.mapAttrs (_: p: p.version) providers else { };
  providerSystems =
    if usable then
      lib.mapAttrs (
        _: targets: map (platform: platforms.${platform}) (builtins.attrNames targets)
      ) downloads
    else
      { };
  toolVersion = data.toolVersion or "";
}
