# Breaks: secret-scan (FR-013). The key below is AWS's own published EXAMPLE value —
# it is inert and grants nothing, but it matches the AKIA pattern the scanner looks for.
provider "aws" {
  region     = "us-east-1"
  access_key = "AKIAIOSFODNN7EXAMPLE"
}
