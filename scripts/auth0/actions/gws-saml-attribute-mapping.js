/**
 * SAML Attribute Mapping for Google Cloud Identity (your-domain.com)
 * Auth0 Action: post-login trigger (v3)
 *
 * Injects department metadata into the SAML assertion for Google Workspace.
 * Google uses NameID (email) for user matching; department is added as a
 * custom attribute for audit trail and future OU-based policy enforcement.
 *
 * User emails: @your-domain.com (unified domain across Auth0 and GWS)
 *
 * SAML App Config:
 *   ACS URL: profile-specific (from Google Admin Console SP Details)
 *   Audience: profile-specific Entity ID (from Google Admin Console SP Details)
 *   NameID Format: urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress
 *
 * Assertion size must stay under 2 KB (Google's limit).
 */
exports.onExecutePostLogin = async (event, api) => {
  // Only add SAML claims for the Google Workspace application
  // Replace with your Auth0 GWS SAML application's client_id
  if (event.client.client_id !== 'YOUR_AUTH0_GWS_SAML_CLIENT_ID') {
    return;
  }

  const department = event.user.user_metadata?.department || 'Unknown';
  const roleTitle = event.user.user_metadata?.role_title || 'Unknown';

  // Inject department and role as custom SAML attributes
  api.samlResponse.setAttribute('department', department);
  api.samlResponse.setAttribute('role_title', roleTitle);

  console.log(
    `GWS SAML attributes set for ${event.user.email}: ` +
    `department=${department}, role_title=${roleTitle}`
  );
};
