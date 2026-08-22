environment = "dev"
vpc_cidr    = "10.10.0.0/16"
azs         = ["us-east-1a", "us-east-1b"]

# --- T129: cost profile decided 2026-08-22. Ephemeral sessions (option 4).
#
# The account is 23 months old, so the 12-month free tier expired 2025-09-17 and no
# credits apply. Every dollar is the database and its plumbing; the whole application
# layer (Lambda, CloudFront, Cognito, CloudWatch, SNS) is Always-Free at demo scale.
#
# Strategy: provision, verify, destroy. Nothing here needs to survive overnight -- the
# remaining AWS-blocked tasks are all verification. ~$0.08/hour, so three ~3h sessions
# cost under a dollar.

# research.md R-003 records this as the sanctioned fallback at demo scale:
# "No proxy at demo scale -- defensible for ten users and worth reconsidering if RDS
# Proxy's cost proves material." It proved material: the proxy is priced per ACU-hour
# with an 8-ACU MINIMUM, so it costs ~$88/mo -- roughly twice the 0.5-ACU cluster it
# pools for. With ~10 concurrent users and SQLAlchemy NullPool, connection exhaustion
# is not a realistic risk.
enable_rds_proxy = false

# Kept warm rather than scale-to-zero: min_acu = 0 would save the remaining compute,
# but adds a ~15s cold start on the first request after idle. For a short verification
# session we are paying for the hours we are actually using anyway, so warmth is free
# in practice and removes a demo risk.
min_acu = 0.5
max_acu = 2

# P2. Off by default; nothing in Phases 1-8 depends on it (Principle VIII).
enable_observability = false
