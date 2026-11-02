# SPDX-License-Identifier: MIT
# Read only the HCL forms emitted by the native dependency lock writer.
{ lib }:
path:
let
  fail = throw "tofu-purifier: malformed .terraform.lock.hcl; run tofu-purifier lock";
  lines = lib.filter (line: line != "" && !(lib.hasPrefix "#" line)) (
    map lib.trim (lib.splitString "\n" (builtins.readFile path))
  );
  state =
    builtins.foldl'
      (
        state: line:
        let
          begin = builtins.match "provider[ ]+\"([^\"]+)\"[ ]*[{]" line;
          version = builtins.match "version[ ]*=[ ]*(\"[^\"]+\")" line;
          constraints = builtins.match "constraints[ ]*=[ ]*(\"[^\"]*\")" line;
          hash = builtins.match "(\"[^\"]+\"),?" line;
        in
        if begin != null then
          if state.current != null || builtins.hasAttr (builtins.head begin) state.providers then
            fail
          else
            state
            // {
              current = builtins.head begin;
              value = { };
            }
        else if state.current == null then
          fail
        else if state.hashes then
          if line == "]" then
            state // { hashes = false; }
          else if hash == null then
            fail
          else
            state
            // {
              value = state.value // {
                hashes = state.value.hashes ++ [ (builtins.fromJSON (builtins.head hash)) ];
              };
            }
        else if version != null then
          if state.value ? version then
            fail
          else
            state
            // {
              value = state.value // {
                version = builtins.fromJSON (builtins.head version);
              };
            }
        else if constraints != null then
          if state.value ? constraints then
            fail
          else
            state
            // {
              value = state.value // {
                constraints = builtins.fromJSON (builtins.head constraints);
              };
            }
        else if line == "hashes = [" then
          if state.value ? hashes then
            fail
          else
            state
            // {
              hashes = true;
              value = state.value // {
                hashes = [ ];
              };
            }
        else if line == "}" then
          state
          // {
            current = null;
            providers = state.providers // {
              ${state.current} = state.value;
            };
          }
        else
          fail
      )
      {
        current = null;
        hashes = false;
        providers = { };
        value = { };
      }
      lines;
in
builtins.addErrorContext "tofu-purifier: cannot read native lock; run tofu-purifier lock" (
  if state.current != null || state.hashes then fail else state.providers
)
