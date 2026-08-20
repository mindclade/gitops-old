<!-- mindclade-doc: reference@1 -->

# Release promotion proposals

Files here are inert review requests. They do not alter an environment selection and Argo CD
does not reconcile them. The protected release promoter may create one new proposal after the
build, qualification, and deployment attestations succeed. Reviewers must verify the complete
evidence set, create the bound `releases/<id>.json` record, and deliberately update
`deployments/development.yaml`; staging and production remain adjacent reviewed promotions.

The promoter cannot overwrite a proposal, choose an arbitrary application, select a mutable
image, or change rendered Kubernetes YAML.

