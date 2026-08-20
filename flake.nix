# Copyright © 2026 Mindclade, LLC. All Rights Reserved.
# Mindclade Proprietary and Confidential.
# SPDX-License-Identifier: LicenseRef-Mindclade-Proprietary

{
  description = "Toolchain for the mindclade gitops repository";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.05";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
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
        devShells.ci = pkgs.mkShell {
          packages = with pkgs; [
            kustomize
            kubeconform
            gatekeeper # provides `gator`
            yq-go

            # The `lint` job in validate.yml. .yamllint.yaml and .github/actionlint.yaml were
            # in this repository with nothing running either of them — and only `default`
            # carried the binaries, which is a shell no workflow resolves.
            actionlint
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
        devShells.evidence = pkgs.mkShell {
          packages = with pkgs; [
            bashInteractive
            curl
            google-cloud-sdk
            jq
          ];
        };

        devShells.default = pkgs.mkShell {
          # OPA is pinned to match build/toolchains/versions.yaml in the monorepo (1.15.2),
          # so a policy that passes locally passes in the monorepo's gates too.
          #
          # Every version here is fixed by flake.lock, which is committed. Without it
          # `nixos-25.05` is a BRANCH resolved at evaluation time, and the toolchain would
          # drift between a laptop and CI with no file in this repository changing.
          packages = with pkgs; [
            kubernetes-helm
            kustomize
            kubeconform
            conftest
            gatekeeper      # provides `gator`, Gatekeeper's own policy evaluator
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
      });
}
