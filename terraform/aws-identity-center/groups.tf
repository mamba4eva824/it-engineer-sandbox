# Identity Store groups mirror Okta access-* entitlement groups for future SAML/SCIM sync.

resource "aws_identitystore_group" "developers" {
  identity_store_id = local.identity_store_id
  display_name      = "Developers"
  description       = "Developer access — Developer permission set (PowerUser) on the sandbox account."
}

resource "aws_identitystore_group" "grc" {
  identity_store_id = local.identity_store_id
  display_name      = "GRC"
  description       = "GRC analyst access — JMLAuditReadOnly permission set on the sandbox account."
}
