# Rollback

Rollback is a reviewed Git revert to the last known-good immutable artifact digest. Do not
edit live Applications or Deployments. Before reverting, check migration compatibility; an
irreversible data migration requires forward recovery. After merge, Argo CD self-heals to the
reviewed state and the deployment evidence links the source, GitOps commit, and sync.
