resource "aws_identitystore_user" "member" {
  for_each = local.all_user_emails

  identity_store_id = local.identity_store_id
  display_name      = each.value
  user_name         = each.value

  name {
    given_name  = split("@", each.value)[0]
    family_name = contains(local.grc_user_emails, each.value) ? "GRC" : "Developer"
  }

  emails {
    value   = each.value
    primary = true
  }
}

resource "aws_identitystore_group_membership" "developers" {
  for_each = local.developer_user_emails

  identity_store_id = local.identity_store_id
  group_id          = aws_identitystore_group.developers.group_id
  member_id         = aws_identitystore_user.member[each.value].user_id
}

resource "aws_identitystore_group_membership" "grc" {
  for_each = local.grc_user_emails

  identity_store_id = local.identity_store_id
  group_id          = aws_identitystore_group.grc.group_id
  member_id         = aws_identitystore_user.member[each.value].user_id
}
