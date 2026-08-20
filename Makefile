.PHONY: license-headers license-headers-fix repository-invariants bootstrap-checks \
        yaml-check project-rbac release-metadata validate-production-contract validate

license-headers:
	bash scripts/license-header-check.sh --check

license-headers-fix:
	bash scripts/license-header-check.sh --fix

repository-invariants:
	python3 scripts/validate-repository.py

bootstrap-checks:
	cd bootstrap && sha256sum -c argocd-install.yaml.sha256 && sha256sum -c argocd-install-ha.yaml.sha256

yaml-check:
	python3 scripts/validate-yaml.py

project-rbac:
	python3 scripts/validate-project-rbac.py

release-metadata:
	python3 scripts/validate-release-metadata.py

validate-production-contract:
	python3 scripts/validate-production-contract.py

validate: validate-production-contract repository-invariants bootstrap-checks yaml-check project-rbac release-metadata
