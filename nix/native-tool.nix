# SPDX-License-Identifier: MIT
{ opentofu }:
opentofu.overrideAttrs (old: {
  patches = (old.patches or [ ]) ++ [ ./native-lockfile.patch ];
})
