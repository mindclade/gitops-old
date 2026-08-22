.PHONY: license-headers license-headers-fix repository-invariants bootstrap-checks arc-render cert-manager-vendor \
        yaml-check project-rbac release-handoff release-metadata release-metadata-tests deployment-selections shell-check \
        production-qualification-tests validate-production-contract validate-repository-home validate-core validate

license-headers:
	python3 scripts/license-header-check.py --check

license-headers-fix:
	python3 scripts/license-header-check.py --fix

repository-invariants:
	python3 scripts/validate-repository.py

bootstrap-checks:
	cd bootstrap && sha256sum -c argocd-install.yaml.sha256 && sha256sum -c argocd-install-ha.yaml.sha256

arc-render:
	python3 scripts/render-arc.py

cert-manager-vendor:
	python3 scripts/validate-cert-manager-vendor.py

yaml-check:
	python3 scripts/validate-yaml.py

project-rbac:
	python3 scripts/validate-project-rbac.py

release-handoff:
	python3 scripts/validate-release-handoff.py

release-metadata:
	python3 scripts/validate-release-metadata.py

release-metadata-tests:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p 'test_*.py'

production-qualification-tests:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_production_qualification tests.test_production_eligibility

deployment-selections:
	python3 scripts/validate-deployment-selections.py

shell-check:
	shellcheck --severity=warning bootstrap/bootstrap.sh

validate-production-contract:
	python3 scripts/validate-production-contract.py

validate-repository-home:
	python3 scripts/validate-repository-home.py --root .

validate: validate-core validate-repository-home

validate-core: validate-production-contract repository-invariants bootstrap-checks arc-render cert-manager-vendor yaml-check project-rbac release-handoff release-metadata deployment-selections release-metadata-tests shell-check
