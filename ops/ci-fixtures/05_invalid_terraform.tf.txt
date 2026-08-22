# Breaks: terraform validate (unsupported argument on a real resource type)
resource "aws_vpc" "fixture_invalid" {
  cidr_block                 = "10.0.0.0/16"
  this_argument_does_not_exist = true
}
