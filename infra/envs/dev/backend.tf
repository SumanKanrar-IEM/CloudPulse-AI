# Remote state, created by infra/bootstrap/ (FR-001a).
# Fill bucket and dynamodb_table from the bootstrap outputs before the first init.

terraform {
  required_version = ">= 1.15.0, < 2.0.0"

  backend "s3" {
    bucket         = "cloudpulse-tfstate-dev-767828743440"
    dynamodb_table = "cloudpulse-tflock-dev"
    key            = "dev/terraform.tfstate"
    region         = "us-east-1"
    encrypt        = true
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}
