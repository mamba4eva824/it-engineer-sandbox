/**
 * SAML Attribute Mapping for AWS IAM Identity Center
 * Auth0 Action: post-login trigger (v3)
 *
 * Maps Auth0 user roles and department metadata to SAML attributes
 * that AWS uses to determine Permission Set assignments.
 *
 * SAML App Config:
 *   NameID Format: urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress
 *   (Must be emailAddress, not persistent — AWS matches NameID to Identity Store username)
 *
 * Role -> Permission Set mapping:
 *   IT-Ops      -> Admin (AdministratorAccess)
 *   Engineering -> PowerUser (PowerUserAccess)
 *   Data        -> PowerUser (PowerUserAccess)
 *   All others  -> ReadOnly (ReadOnlyAccess)
 */
exports.onExecutePostLogin = async (event, api) => {
  // Only add SAML claims for the AWS IAM Identity Center application
  // Replace with your Auth0 SAML application's client_id
  if (event.client.client_id !== 'YOUR_AUTH0_SAML_CLIENT_ID') {
    return;
  }

  const department = event.user.user_metadata?.department || 'Unknown';
  const roleTitle = event.user.user_metadata?.role_title || 'Unknown';

  // Map department to AWS Permission Set
  const permissionSetMap = {
    'IT-Ops': 'Admin',
    'Engineering': 'PowerUser',
    'Data': 'PowerUser',
    'Finance': 'ReadOnly',
    'Executive': 'ReadOnly',
    'Product': 'ReadOnly',
    'Design': 'ReadOnly',
    'HR': 'ReadOnly',
    'Sales': 'ReadOnly',
    'Marketing': 'ReadOnly'
  };

  const awsPermissionSet = permissionSetMap[department] || 'ReadOnly';

  // Set SAML attributes for AWS IAM Identity Center
  api.samlResponse.setAttribute(
    'https://aws.amazon.com/SAML/Attributes/RoleSessionName',
    event.user.email
  );

  api.samlResponse.setAttribute(
    'https://aws.amazon.com/SAML/Attributes/SessionDuration',
    '28800'
  );

  // Custom attribute for Permission Set selection
  api.samlResponse.setAttribute(
    'https://aws.amazon.com/SAML/Attributes/AccessLevel',
    awsPermissionSet
  );

  api.samlResponse.setAttribute('department', department);
  api.samlResponse.setAttribute('role_title', roleTitle);

  console.log(
    `SAML attributes set for ${event.user.email}: ` +
    `department=${department}, permissionSet=${awsPermissionSet}`
  );
};
