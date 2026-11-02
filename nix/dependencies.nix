# SPDX-License-Identifier: MIT
{
  lib,
  stdenv,
  runCommand,
  fetchurl,
  fetchgit,
  unzip,
  zstd,
  purifier,
}:
{
  lock,
  fetchers ? { },
}:
let
  checked = purifier.checkLock lock;
in
purifier.tree (
  {
    name = "tofu-dependencies";
    entries = lib.filter (
      e: !(e ? systems) || builtins.elem stdenv.hostPlatform.system e.systems
    ) checked.entries;
    inherit
      runCommand
      fetchurl
      fetchgit
      unzip
      zstd
      ;
  }
  // fetchers
)
