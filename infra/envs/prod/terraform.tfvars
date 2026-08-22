environment = "prod"
vpc_cidr    = "10.20.0.0/16"
azs         = ["us-east-1a", "us-east-1b"]

# Prod-only protections (FR-005a, FR-005b, R-010). Two layers, not three -- Terraform
# cannot make `prevent_destroy` conditional on environment, so that layer was corrected
# out of the spec (see research.md R-010, task T130). What remains: `deletion_protection`
# on the cluster, and the ops/teardown.sh workspace guard, which is the only layer that
# refuses BEFORE touching anything -- what the "teardown aimed at prod" edge case
# requires. Destroying prod deliberately therefore needs one out-of-band step beyond
# `terraform destroy`: disabling deletion_protection on the live cluster first.

# --- Cost profile (T129 decision, mirrored for prod): ephemeral verification session,
# not a persistent environment. Same reasoning as dev's tfvars: the account's 12-month
# free tier expired and no credits apply, so every dollar here is deliberate.
#
# research.md R-003's sanctioned fallback: no RDS Proxy at demo scale. It is priced
# per ACU-hour with an 8-ACU MINIMUM, so it costs roughly twice the 0.5-ACU cluster it
# pools for. With NullPool and demo-scale traffic, connection exhaustion is not a
# realistic risk.
enable_rds_proxy = false

# Kept warm rather than scale-to-zero: for a short verification session we pay for the
# hours we use regardless, so warmth is free in practice and removes a cold-start risk
# during T109's smoke test.
min_acu = 0.5
max_acu = 2

# P2. Off by default; nothing in Phases 1-8 depends on it (Principle VIII).
enable_observability = false
