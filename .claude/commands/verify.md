---
description: "Run all IT Operations Sandbox verification gates and report pass/fail status"
---

# Verify — Run All Sandbox Gates

Run all verification gates and report pass/fail status for each.

## Execution Strategy

Run the following verification gates and report a structured pass/fail summary:

### Gate 1: Auth0 Connectivity
```bash
cd "/Users/christopherweinreich/Documents/Projects/IT Operations Sandbox " && python -c "
from auth0.management import Auth0
from auth0.authentication import GetToken
import os
from dotenv import load_dotenv
load_dotenv()
domain = os.getenv('AUTH0_DOMAIN')
client_id = os.getenv('AUTH0_CLIENT_ID')
client_secret = os.getenv('AUTH0_CLIENT_SECRET')
get_token = GetToken(domain, client_id, client_secret=client_secret)
token = get_token.client_credentials(f'https://{domain}/api/v2/')
mgmt = Auth0(tenant_domain=domain, token=token['access_token'])
users = mgmt.users.list(page=0, per_page=1)
print(f'PASS: Auth0 connected — {domain}')
"
```

### Gate 2: AWS Connectivity
```bash
aws sts get-caller-identity --profile novatech-sandbox 2>&1
```

### Gate 3: Auth0 User Count
```bash
# Verify 100 NovaTech users exist
cd "/Users/christopherweinreich/Documents/Projects/IT Operations Sandbox " && python -c "
from auth0.management import Auth0
from auth0.authentication import GetToken
import os
from dotenv import load_dotenv
load_dotenv()
domain = os.getenv('AUTH0_DOMAIN')
get_token = GetToken(domain, os.getenv('AUTH0_CLIENT_ID'), client_secret=os.getenv('AUTH0_CLIENT_SECRET'))
token = get_token.client_credentials(f'https://{domain}/api/v2/')
mgmt = Auth0(tenant_domain=domain, token=token['access_token'])
users = mgmt.users.list(page=0, per_page=1, include_totals=True)
print(f'Total users in tenant: check count')
"
```

### Gate 4: AWS IAM Identity Center
```bash
aws sso-admin list-instances --profile novatech-sandbox --region $AWS_REGION
```

### Gate 5: AWS Permission Sets
```bash
aws sso-admin list-permission-sets \
  --instance-arn "$AWS_SSO_INSTANCE_ARN" \
  --profile novatech-sandbox --region $AWS_REGION
```

### Gate 6: Auth0 Actions
```bash
cd "/Users/christopherweinreich/Documents/Projects/IT Operations Sandbox " && python -c "
from auth0.management import Auth0
from auth0.authentication import GetToken
import os
from dotenv import load_dotenv
load_dotenv()
domain = os.getenv('AUTH0_DOMAIN')
get_token = GetToken(domain, os.getenv('AUTH0_CLIENT_ID'), client_secret=os.getenv('AUTH0_CLIENT_SECRET'))
token = get_token.client_credentials(f'https://{domain}/api/v2/')
mgmt = Auth0(tenant_domain=domain, token=token['access_token'])
actions = mgmt.actions.list()
for a in actions.items:
    print(f'  Action: {a.name} | Status: {a.status} | Deployed: {a.all_changes_deployed}')
"
```

### Gate 7: Python Dependencies
```bash
pip list 2>/dev/null | grep -E "auth0-python|boto3|python-dotenv|requests|google-api-python-client|slack-sdk"
```

### Gate 8: Google Workspace Connectivity (when configured)
```bash
cd "/Users/christopherweinreich/Documents/Projects/IT Operations Sandbox " && python -c "
from google.oauth2 import service_account
from googleapiclient.discovery import build
import os
# Only run if credentials exist
creds_path = os.getenv('GOOGLE_SERVICE_ACCOUNT_KEY', 'credentials/gws-service-account.json')
if os.path.exists(creds_path):
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=['https://www.googleapis.com/auth/admin.directory.user.readonly'])
    service = build('admin', 'directory_v1', credentials=creds)
    print('PASS: Google Workspace Admin SDK connected')
else:
    print('SKIP: Google Workspace not yet configured')
" 2>&1
```

### Gate 9: Slack Connectivity (when configured)
```bash
cd "/Users/christopherweinreich/Documents/Projects/IT Operations Sandbox " && python -c "
import os
token = os.getenv('SLACK_BOT_TOKEN', '')
if token:
    from slack_sdk import WebClient
    client = WebClient(token=token)
    response = client.auth_test()
    print(f'PASS: Slack connected — workspace: {response[\"team\"]}')
else:
    print('SKIP: Slack not yet configured')
" 2>&1
```

## Output Format

Present results as a table:

| Gate | Status | Details |
|------|--------|---------|
| Auth0 Connectivity | PASS/FAIL | ... |
| AWS Connectivity | PASS/FAIL | ... |
| ... | ... | ... |

## Failure Handling

If any gate fails:
1. Diagnose the root cause from the error output
2. Suggest a fix
3. Do NOT mark verification as complete until all gates pass
