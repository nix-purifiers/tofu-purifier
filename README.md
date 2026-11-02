# tofu-purifier

Locked, Nix-resolved providers and modules for OpenTofu.

## Quickstart

In your existing OpenTofu project:

```sh
nix shell 'github:nix-purifiers/tofu-purifier'
tofu-purifier lock
tofu-purifier prefetch
tofu init
tofu validate
tofu plan
```

Commit `.terraform.lock.hcl` and `tofu-purifier.lock.json`. Provider versions
and checksums stay in the native lock; the companion records download URLs
and immutable Git module pins. Prefetch connects the normal provider and
module caches to Nix store dependencies. OpenTofu runs in your working tree.

This integration uses a wrapper supplied by `nix shell`. You can install it
through your normal Nix configuration if you want it permanently. Without
a purifier lock it warns and runs ordinary, impure OpenTofu. Invalid or stale
locks fail with a repair command.

## Development loop

After changing configuration:

```sh
nix shell 'github:nix-purifiers/tofu-purifier'
tofu fmt
tofu-purifier lock
tofu-purifier prefetch
tofu validate
tofu test
```

Locking retains existing provider selections and valid Git module pins,
including when an upstream branch moves. Repeating `lock` without changes
leaves both lockfiles byte-for-byte identical. Update provider selections
and module revisions through the native upgrade operation:

```sh
tofu-purifier update
tofu-purifier prefetch
```

OpenTofu has no native targeted provider/module upgrade command, so named
updates are not supported. To change one dependency, edit its version or
source constraint and run `lock`. The wrapper directs native upgrade and
provider-mirroring commands through the purifier CLI.

Configuration fingerprints cover root/local-module `.tf`, `.tf.json`,
`.tofu`, `.tofu.json` files and their default test directories. Relock after
editing those files. Formatting and version commands remain available
without a prefetch.

## Working offline

```sh
nix shell 'github:nix-purifiers/tofu-purifier'
tofu-purifier prefetch
tofu init -backend=false
tofu validate
tofu test
```

Prefetch roots the dependencies, native tool and editor worker beside the
selected lock. The wrapper supplies an exclusive local plugin directory to
`init`, disables module downloading there, and selects a read-only provider
lock. It preserves normal backend options; backend initialization and cloud
operations may need their usual network access. The dependency-only offline
checks use `-backend=false` and plan tests.

Generated provider/module cache entries point at immutable store paths.
Existing cache entries are retained with `.before-purifier` suffixes when
first replaced. Backend state is left alone. `TF_DATA_DIR` is supported.
No project Nix files or generated development shell are needed.

## Editor

Start `tofu-ls serve` from the same shell. Prefetch supplies the language
server, provider binaries, schemas available from those binaries, and Git
module sources. Native cache metadata lets definition lookup reach the
locked modules. The editor check verifies that lookup in the Nix sandbox.

## Troubleshooting

- **Configuration or native lock changed:** run `tofu-purifier lock`, then
  `prefetch`.
- **Missing provider/module entry:** `lock` repairs the companion against
  the native resolution. A damaged companion may require resolving module
  sources again if their previous pins cannot be recovered.
- **Wrong OpenTofu version:** use the wrapper, or override the scope's
  `nativeTool` and regenerate the companion using that toolchain.
- **Cache backup already exists:** move the additional cache entry aside
  before prefetching. Existing backups are preserved.
- **A different provider platform is needed:** add another supported platform
  when locking. The default records Linux AMD64 and ARM64.

```sh
tofu-purifier lock --platform linux_amd64
```

External native and companion locks are supported without replacing the
working tree's native lock:

```sh
tofu-purifier \
  --tofu-lock ../locks/providers.hcl \
  --lockfile ../locks/tofu.json lock
tofu-purifier \
  --tofu-lock ../locks/providers.hcl \
  --lockfile ../locks/tofu.json prefetch
```

Set `TOFU_PURIFIER_TOFU_LOCK` and `TOFU_PURIFIER_LOCKFILE` to the same paths
for the native wrapper. A missing external provider lock starts from the
working tree's copy. The delivered OpenTofu has a small opt-in extension
for an external lock path; its normal default path and behavior are unchanged.
The wrapper also follows the native `-chdir` option.

## Supported language repositories

Public provider registries implementing the native service-discovery and
provider-download protocols are supported. Archive checksums are selected
from the native `zh:` hashes; provider versions and checksums are not copied
into the companion. Provider packages are unpacked through Nix fetchers.

Git and local modules are supported, including Git subdirectories and nested
module calls. Registry modules are supported when their installed source is
Git-backed. Git modules use fixed commits and NAR hashes; local module files
remain in the source. Non-Git downloaded module archives and computed module
source/version expressions are not yet supported. Use literal coordinates.
The flake targets x86_64 and ARM Linux.

The native HCL lock reader runs during Nix evaluation without
import-from-derivation. No native plugin package repository is needed;
GitHub Pages hosts this documentation.

## Examples

[`examples/random`](examples/random) combines the Random provider and a
pinned Git module. Its test plans the configuration and checks a module
output:

```sh
nix shell 'github:nix-purifiers/tofu-purifier'
cd examples/random
tofu-purifier prefetch
tofu init -backend=false
tofu test
```

Checks validate the configuration, execute the plan test, resolve module
outputs in the real language server, reject unusable locks in independent
Nix/Python readers, and build with external locks. Native Git-daemon tests
cover nested modules, retained pins and explicit upgrades, then stop the
server before validating and testing offline. External-lock tests leave a
deliberately different working-tree lock untouched.

### Optional Nix build

The overlay adds only the `tofu-purifier` scope:

```nix
let
  pkgs = import nixpkgs {
    inherit system;
    overlays = [ purifier.overlays.default ];
  };
  project = pkgs.tofu-purifier.buildTofuProject {
    src = ./.;
    tofuLock = ../locks/providers.hcl;
    lockFile = ../locks/tofu.json;
  };
in {
  packages.default = project.packages.configuration;
  checks.default = project.tests;
}
```

The result exposes `packages.configuration`, `tests`, `release` and
`fetches`. The builder takes named `callPackage` dependencies and supports
`fetchers`, `srcFilter`, `testCommand` and scope overrides. Initialization
and validation run offline; the default test command is `tofu test`.

State, saved plan files, variable input files and generated caches are
excluded from the packaged source by default. `release` is a deterministic
source archive containing the selected locks. Upload that Nix-built artifact
to a GitHub release with:

```sh
tofu-purifier publish \
  --repo OWNER/PROJECT --tag v1.0.0
```

`lib.tofu-purifier.readLock` exposes the shared in-memory lock shape. CI
checks configuration and release reproducibility with `nix build --rebuild`.

## Credits

The purifier idea was inspired by nixcloud's
[cargo (libnix)](https://github.com/nixcloud/cargo).
