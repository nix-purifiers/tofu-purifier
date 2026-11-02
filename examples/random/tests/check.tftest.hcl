run "label" {
  command = plan
  assert {
    condition = output.label == "purifier-test-hello"
    error_message = "The locked module did not produce the expected label."
  }
}
