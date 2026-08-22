environment = "prod"
vpc_cidr    = "10.20.0.0/16"
azs         = ["us-east-1a", "us-east-1b"]

# Prod-only protections (FR-005a, FR-005b, R-010). Layer 1 of three; the other two
# are `prevent_destroy` on the cluster and the ops/teardown.sh workspace guard.
# The teardown guard is the only layer that refuses BEFORE touching anything, which
# is what the "teardown aimed at prod" edge case requires.
