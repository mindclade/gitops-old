.PHONY: license-headers license-headers-fix repository-invariants bootstrap-checks \
        yaml-check project-rbac release-metadata release-metadata-tests deployment-selections shell-check \
        validate-production-contract validate

license-headers:
	python3 scripts/license-header-check.py --check

license-headers-fix:
	python3 scripts/license-header-check.py --fix

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

release-metadata-tests:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'

deployment-selections:
	python3 scripts/validate-deployment-selections.py

shell-check:
	shellcheck --severity=warning bootstrap/bootstrap.sh

validate-production-contract:
	python3 scripts/validate-production-contract.py

validate: validate-production-contract repository-invariants bootstrap-checks yaml-check project-rbac release-metadata deployment-selections release-metadata-tests shell-check
