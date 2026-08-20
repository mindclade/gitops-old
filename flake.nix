# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

{
  description = "Toolchain for the mindclade gitops repository";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs =
    { nixpkgs, ... }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
        "aarch64-darwin"
        "x86_64-darwin"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      perSystem =
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          ciShell = pkgs.mkShell {
            # ---------------------------------------------------------------------------------
            # CI shell
            # ---------------------------------------------------------------------------------
            # The four tools CI needs, and nothing else.
            #
            # These used to be installed by `curl`-ing a release tarball onto PATH with nothing
            # verifying what came back — in the repository whose scripts/render.py refuses to
            # render a remote base that does not match a recorded sha256 and byte count. The tool
            # enforcing that rule was itself unverified. Taking them from the flake removes the
            # download rather than authenticating it: flake.lock pins the exact nixpkgs revision,
            # and Nix checks every store path against its hash.
            #
            # SEPARATE FROM `default` because that shell also carries google-cloud-sdk, helm,
            # kubectl and OPA — a large closure for a job that needs one binary. `default` stays
            # the full local toolchain; this is what `nix develop .#ci` in a workflow resolves.
            packages = with pkgs; [
              kustomize
              kubeconform
              gatekeeper # provides `gator`
              yq-go
              git

              # The `lint` job in validate.yml. .yamllint.yaml and .github/actionlint.yaml were
              # in this repository with nothing running either of them — and only `default`
              # carried the binaries, which is a shell no workflow resolves.
              actionlint
              gnumake
              shellcheck # actionlint shells out to it for `run:` blocks
              yamllint
              (python3.withPackages (pythonPackages: [
                pythonPackages.jsonschema
                pythonPackages.pyyaml
              ]))
            ];
          };

          # External release-evidence verification. Keeping gcloud in a separate shell avoids
          # making every YAML/schema job build the large Google Cloud SDK closure. Its version is
          # still fixed by flake.lock rather than inherited from the runner.
          evidenceShell = pkgs.mkShell {
            packages = with pkgs; [
              bashInteractive
              curl
              google-cloud-sdk
              jq
            ];
          };

          defaultShell = pkgs.mkShell {
            # OPA 1.6.0 is pinned by this repository's flake.lock. Keep the monorepo policy
            # toolchain on the same release when its version catalog is updated.
            #
            # Every version here is fixed by flake.lock, which is committed. Without it
            # `nixos-26.05` is a branch resolved at lock-update time, and the toolchain would
            # drift between a laptop and CI with no file in this repository changing.
            packages = with pkgs; [
              kubernetes-helm
              kustomize
              kubeconform
              conftest
              gatekeeper # provides `gator`, Gatekeeper's own policy evaluator
              open-policy-agent
              kubectl
              cosign
              google-cloud-sdk
              yq-go
              jq
              yamllint
              actionlint
              (python3.withPackages (pythonPackages: [
                pythonPackages.jsonschema
                pythonPackages.pyyaml
              ]))

              # bash 5. macOS ships 3.2; promote.yml and the render path use bash 4+ builtins,
              # and a script that only works in CI is a script nobody can debug locally.
              bashInteractive
            ];

            shellHook = ''
              echo "gitops"
              echo
              echo "  rendered/ IS GENERATED. Never hand-edit it — render.yml re-renders and"
              echo "  diffs on every PR, and the reversion looks like the cluster changing on"
              echo "  its own."
              echo
              echo "  python3 scripts/render.py --monorepo ../../mindclade-github/mindclade-internal-monorepo --write"
              echo "  python3 scripts/render.py --monorepo <path>     # what CI runs"
              echo "  kubeconform -strict -summary -ignore-missing-schemas rendered/"
              echo "  gator test --filename=policy/templates --filename=policy/constraints \\"
              echo "             --filename=rendered/development"
            '';
          };
        in
        {
          inherit
            ciShell
            defaultShell
            evidenceShell
            pkgs
            ;
        };
    in
    {
      devShells = forAllSystems (system: {
        ci = (perSystem system).ciShell;
        default = (perSystem system).defaultShell;
        evidence = (perSystem system).evidenceShell;
      });

      # The CI shell is the credential-free validation contract. The evidence shell is kept
      # out of checks because it exists only for protected, externally authenticated workflows.
      checks = forAllSystems (system: {
        ci-shell = (perSystem system).ciShell;
      });

      formatter = forAllSystems (system: (perSystem system).pkgs.nixfmt);
    };
}
