terraform {
  required_providers {
    random = {
      source = "hashicorp/random"
      version = "~> 3.7"
    }
  }
}
module "label" {
  source = "git::https://github.com/cloudposse/terraform-null-label.git?ref=38364d79c1082de13373666252e1276975919543"
  namespace = "purifier"
  stage = "test"
  name = "hello"
}
resource "random_integer" "example" {
  min = 1
  max = 9
}
output "label" {
  value = module.label.id
}
