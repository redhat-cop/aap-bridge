# Credential Comparison Report

**Total Source Credentials:** 57
**Total Target Credentials:** 54
**Matching Credentials:** 14
**Missing in Target:** 42
**Managed Credentials (Skipped):** 1

---

## Missing Credentials

The following credentials exist in source but are missing in target:

| Source ID | Name | Type | Organization | Description |
|-----------|------|------|--------------|-------------|
| 6 | Automation Hub Community Repository | Ansible Galaxy/Automation Hub API Token | None |  |
| 7 | Automation Hub Container Registry | Container Registry | None |  |
| 4 | Automation Hub Published Repository | Ansible Galaxy/Automation Hub API Token | None |  |
| 5 | Automation Hub RH Certified Repository | Ansible Galaxy/Automation Hub API Token | None |  |
| 3 | Automation Hub Validated Repository | Ansible Galaxy/Automation Hub API Token | None |  |
| 29 | Azure Subscription 33 | Microsoft Azure Resource Manager | Cloud Services | Azure Resource Manager credential |
| 31 | Azure Subscription 35 | Microsoft Azure Resource Manager | IT Operations | Azure Resource Manager credential |
| 1 | Demo Credential | Machine | None |  |
| 20 | Development HashiCorp Vault | HashiCorp Vault Secret Lookup | Global Engineering | HashiCorp Vault for development environment using  |
| 10 | Development SSH Key | Machine | Engineering | SSH key for development servers (placeholder - add |
| 57 | E2E-AWS-Cred | Amazon Web Services | E2E-Test-Galaxy-Org |  |
| 55 | E2E-Git-Token | Source Control | E2E-Test-Simple-Org |  |
| 54 | E2E-Machine-Password | Machine | E2E-Test-Simple-Org |  |
| 56 | E2E-Vault-Cred | Vault | E2E-Test-Simple-Org |  |
| 42 | Final Test AWS 12 | Amazon Web Services | DevOps Platform | Final validation AWS credential #12 |
| 43 | Final Test Azure 13 | Microsoft Azure Resource Manager | Security & Compliance | Final validation Azure credential #13 |
| 46 | Final Test Galaxy 16 | Ansible Galaxy/Automation Hub API Token | Cloud Services | Final validation Galaxy credential #16 |
| 48 | Final Test GitHub Token 18 | GitHub Personal Access Token | Global Engineering | Final validation GitHub token |
| 49 | Final Test GitLab Token 19 | GitLab Personal Access Token | Engineering | Final validation GitLab token |
| 39 | Final Test SCM 7 | Source Control | IT Operations | Final validation SCM credential #7 |
| 40 | Final Test SCM 8 | Source Control | Cloud Services | Final validation SCM credential #8 |
| 38 | Final Test SSH 2 | Machine | DevOps Platform | Final validation SSH credential #2 |
| 50 | Final Test Vault Password 20 | Vault | DevOps Platform | Final validation Vault password |
| 33 | Galaxy/Hub Token 47 | Ansible Galaxy/Automation Hub API Token | Global Engineering | Automation Hub API token |
| 34 | Galaxy/Hub Token 48 | Ansible Galaxy/Automation Hub API Token | IT Operations | Automation Hub API token |
| 35 | Galaxy/Hub Token 49 | Ansible Galaxy/Automation Hub API Token | Engineering | Automation Hub API token |
| 36 | Galaxy/Hub Token 50 | Ansible Galaxy/Automation Hub API Token | DevOps Platform | Automation Hub API token |
| 12 | GitHub Backup Repository | Source Control | Engineering | GitHub credentials for backup repository |
| 11 | GitHub Main Repository | Source Control | Engineering | GitHub credentials for main repository |
| 13 | GitLab Enterprise | Source Control | Engineering | GitLab credentials for enterprise repos |
| 21 | Kubernetes HashiCorp Vault | HashiCorp Vault Secret Lookup | Cloud Services | HashiCorp Vault using Kubernetes service account a |
| 17 | Private GitHub Token | Git Personal Access Token | Global Engineering | Personal access token for private repos |
| 14 | Production API Token | API Token | IT Operations | API token for production services |
| 15 | Production Database | Database Connection | IT Operations | Production PostgreSQL database |
| 19 | Production HashiCorp Vault | HashiCorp Vault Secret Lookup | IT Operations | HashiCorp Vault server for secret management and c |
| 9 | Production SSH Key | Machine | Engineering | SSH key for production servers (placeholder - add  |
| 52 | REGRESSION_TEST_Git_Cred_002 | Source Control | Global Engineering | Regression test Git credential for credential-firs |
| 51 | REGRESSION_TEST_Machine_Cred_001 | Machine | Engineering | Regression test credential for credential-first mi |
| 18 | ServiceNow Production | ServiceNow | IT Operations | ServiceNow production instance |
| 16 | Slack Notifications | Notification Webhook | DevOps Platform | Slack webhook for job notifications |
| 23 | Vault-Backed AWS Credential | Amazon Web Services | Cloud Services | AWS credentials dynamically retrieved from HashiCo |
| 22 | Vault-Backed SSH Credential | Machine | IT Operations | SSH credential with secrets pulled from HashiCorp  |

### Details

#### 1. Automation Hub Community Repository
- **Source ID:** 6
- **Type:** Ansible Galaxy/Automation Hub API Token (ID: 19)
- **Organization: None (Global)**
- **Description:** 
- **Inputs:** `['url', 'token']` (values are encrypted)

#### 2. Automation Hub Container Registry
- **Source ID:** 7
- **Type:** Container Registry (ID: 18)
- **Organization: None (Global)**
- **Description:** 
- **Inputs:** `['host', 'password', 'username', 'verify_ssl']` (values are encrypted)

#### 3. Automation Hub Published Repository
- **Source ID:** 4
- **Type:** Ansible Galaxy/Automation Hub API Token (ID: 19)
- **Organization: None (Global)**
- **Description:** 
- **Inputs:** `['url', 'token']` (values are encrypted)

#### 4. Automation Hub RH Certified Repository
- **Source ID:** 5
- **Type:** Ansible Galaxy/Automation Hub API Token (ID: 19)
- **Organization: None (Global)**
- **Description:** 
- **Inputs:** `['url', 'token']` (values are encrypted)

#### 5. Automation Hub Validated Repository
- **Source ID:** 3
- **Type:** Ansible Galaxy/Automation Hub API Token (ID: 19)
- **Organization: None (Global)**
- **Description:** 
- **Inputs:** `['url', 'token']` (values are encrypted)

#### 6. Azure Subscription 33
- **Source ID:** 29
- **Type:** Microsoft Azure Resource Manager (ID: 10)
- **Organization: Cloud Services (ID: 8)**
- **Description:** Azure Resource Manager credential
- **Inputs:** `['client', 'secret', 'tenant', 'subscription']` (values are encrypted)

#### 7. Azure Subscription 35
- **Source ID:** 31
- **Type:** Microsoft Azure Resource Manager (ID: 10)
- **Organization: IT Operations (ID: 6)**
- **Description:** Azure Resource Manager credential
- **Inputs:** `['client', 'secret', 'tenant', 'subscription']` (values are encrypted)

#### 8. Demo Credential
- **Source ID:** 1
- **Type:** Machine (ID: 1)
- **Organization: None (Global)**
- **Description:** 
- **Inputs:** `['username']` (values are encrypted)

#### 9. Development HashiCorp Vault
- **Source ID:** 20
- **Type:** HashiCorp Vault Secret Lookup (ID: 26)
- **Organization: Global Engineering (ID: 5)**
- **Description:** HashiCorp Vault for development environment using token authentication
- **Inputs:** `['url', 'token', 'namespace', 'api_version']` (values are encrypted)

#### 10. Development SSH Key
- **Source ID:** 10
- **Type:** Machine (ID: 1)
- **Organization: Engineering (ID: 4)**
- **Description:** SSH key for development servers (placeholder - add key manually)
- **Inputs:** `['username']` (values are encrypted)

#### 11. E2E-AWS-Cred
- **Source ID:** 57
- **Type:** Amazon Web Services (ID: 5)
- **Organization: E2E-Test-Galaxy-Org (ID: 11)**
- **Description:** 
- **Inputs:** `['password', 'username']` (values are encrypted)

#### 12. E2E-Git-Token
- **Source ID:** 55
- **Type:** Source Control (ID: 2)
- **Organization: E2E-Test-Simple-Org (ID: 10)**
- **Description:** 
- **Inputs:** `['password', 'username']` (values are encrypted)

#### 13. E2E-Machine-Password
- **Source ID:** 54
- **Type:** Machine (ID: 1)
- **Organization: E2E-Test-Simple-Org (ID: 10)**
- **Description:** 
- **Inputs:** `['password', 'username']` (values are encrypted)

#### 14. E2E-Vault-Cred
- **Source ID:** 56
- **Type:** Vault (ID: 3)
- **Organization: E2E-Test-Simple-Org (ID: 10)**
- **Description:** 
- **Inputs:** `['vault_id', 'vault_password']` (values are encrypted)

#### 15. Final Test AWS 12
- **Source ID:** 42
- **Type:** Amazon Web Services (ID: 5)
- **Organization: DevOps Platform (ID: 9)**
- **Description:** Final validation AWS credential #12
- **Inputs:** `['password', 'username']` (values are encrypted)

#### 16. Final Test Azure 13
- **Source ID:** 43
- **Type:** Microsoft Azure Resource Manager (ID: 10)
- **Organization: Security & Compliance (ID: 7)**
- **Description:** Final validation Azure credential #13
- **Inputs:** `['client', 'secret', 'tenant', 'subscription']` (values are encrypted)

#### 17. Final Test Galaxy 16
- **Source ID:** 46
- **Type:** Ansible Galaxy/Automation Hub API Token (ID: 19)
- **Organization: Cloud Services (ID: 8)**
- **Description:** Final validation Galaxy credential #16
- **Inputs:** `['url', 'token']` (values are encrypted)

#### 18. Final Test GitHub Token 18
- **Source ID:** 48
- **Type:** GitHub Personal Access Token (ID: 11)
- **Organization: Global Engineering (ID: 5)**
- **Description:** Final validation GitHub token
- **Inputs:** `['token']` (values are encrypted)

#### 19. Final Test GitLab Token 19
- **Source ID:** 49
- **Type:** GitLab Personal Access Token (ID: 12)
- **Organization: Engineering (ID: 4)**
- **Description:** Final validation GitLab token
- **Inputs:** `['token']` (values are encrypted)

#### 20. Final Test SCM 7
- **Source ID:** 39
- **Type:** Source Control (ID: 2)
- **Organization: IT Operations (ID: 6)**
- **Description:** Final validation SCM credential #7
- **Inputs:** `['username']` (values are encrypted)

#### 21. Final Test SCM 8
- **Source ID:** 40
- **Type:** Source Control (ID: 2)
- **Organization: Cloud Services (ID: 8)**
- **Description:** Final validation SCM credential #8
- **Inputs:** `['password', 'username']` (values are encrypted)

#### 22. Final Test SSH 2
- **Source ID:** 38
- **Type:** Machine (ID: 1)
- **Organization: DevOps Platform (ID: 9)**
- **Description:** Final validation SSH credential #2
- **Inputs:** `['password', 'username', 'become_method']` (values are encrypted)

#### 23. Final Test Vault Password 20
- **Source ID:** 50
- **Type:** Vault (ID: 3)
- **Organization: DevOps Platform (ID: 9)**
- **Description:** Final validation Vault password
- **Inputs:** `['vault_password']` (values are encrypted)

#### 24. Galaxy/Hub Token 47
- **Source ID:** 33
- **Type:** Ansible Galaxy/Automation Hub API Token (ID: 19)
- **Organization: Global Engineering (ID: 5)**
- **Description:** Automation Hub API token
- **Inputs:** `['url', 'token']` (values are encrypted)

#### 25. Galaxy/Hub Token 48
- **Source ID:** 34
- **Type:** Ansible Galaxy/Automation Hub API Token (ID: 19)
- **Organization: IT Operations (ID: 6)**
- **Description:** Automation Hub API token
- **Inputs:** `['url', 'token']` (values are encrypted)

#### 26. Galaxy/Hub Token 49
- **Source ID:** 35
- **Type:** Ansible Galaxy/Automation Hub API Token (ID: 19)
- **Organization: Engineering (ID: 4)**
- **Description:** Automation Hub API token
- **Inputs:** `['url', 'token']` (values are encrypted)

#### 27. Galaxy/Hub Token 50
- **Source ID:** 36
- **Type:** Ansible Galaxy/Automation Hub API Token (ID: 19)
- **Organization: DevOps Platform (ID: 9)**
- **Description:** Automation Hub API token
- **Inputs:** `['url', 'token']` (values are encrypted)

#### 28. GitHub Backup Repository
- **Source ID:** 12
- **Type:** Source Control (ID: 2)
- **Organization: Engineering (ID: 4)**
- **Description:** GitHub credentials for backup repository
- **Inputs:** `['password', 'username']` (values are encrypted)

#### 29. GitHub Main Repository
- **Source ID:** 11
- **Type:** Source Control (ID: 2)
- **Organization: Engineering (ID: 4)**
- **Description:** GitHub credentials for main repository
- **Inputs:** `['password', 'username']` (values are encrypted)

#### 30. GitLab Enterprise
- **Source ID:** 13
- **Type:** Source Control (ID: 2)
- **Organization: Engineering (ID: 4)**
- **Description:** GitLab credentials for enterprise repos
- **Inputs:** `['password', 'username']` (values are encrypted)

#### 31. Kubernetes HashiCorp Vault
- **Source ID:** 21
- **Type:** HashiCorp Vault Secret Lookup (ID: 26)
- **Organization: Cloud Services (ID: 8)**
- **Description:** HashiCorp Vault using Kubernetes service account authentication
- **Inputs:** `['url', 'namespace', 'api_version', 'kubernetes_role', 'default_auth_path']` (values are encrypted)

#### 32. Private GitHub Token
- **Source ID:** 17
- **Type:** Git Personal Access Token (ID: 35)
- **Organization: Global Engineering (ID: 5)**
- **Description:** Personal access token for private repos
- **Inputs:** `['git_host', 'git_token', 'git_username']` (values are encrypted)

#### 33. Production API Token
- **Source ID:** 14
- **Type:** API Token (ID: 30)
- **Organization: IT Operations (ID: 6)**
- **Description:** API token for production services
- **Inputs:** `['api_url', 'api_token', 'verify_ssl']` (values are encrypted)

#### 34. Production Database
- **Source ID:** 15
- **Type:** Database Connection (ID: 31)
- **Organization: IT Operations (ID: 6)**
- **Description:** Production PostgreSQL database
- **Inputs:** `['db_host', 'db_name', 'db_port', 'db_password', 'db_ssl_mode', 'db_username']` (values are encrypted)

#### 35. Production HashiCorp Vault
- **Source ID:** 19
- **Type:** HashiCorp Vault Secret Lookup (ID: 26)
- **Organization: IT Operations (ID: 6)**
- **Description:** HashiCorp Vault server for secret management and credential injection
- **Inputs:** `['url', 'token', 'cacert', 'role_id', 'namespace', 'secret_id', 'api_version', 'default_auth_path']` (values are encrypted)

#### 36. Production SSH Key
- **Source ID:** 9
- **Type:** Machine (ID: 1)
- **Organization: Engineering (ID: 4)**
- **Description:** SSH key for production servers (placeholder - add key manually)
- **Inputs:** `['username']` (values are encrypted)

#### 37. REGRESSION_TEST_Git_Cred_002
- **Source ID:** 52
- **Type:** Source Control (ID: 2)
- **Organization: Global Engineering (ID: 5)**
- **Description:** Regression test Git credential for credential-first migration
- **Inputs:** `['password', 'username']` (values are encrypted)

#### 38. REGRESSION_TEST_Machine_Cred_001
- **Source ID:** 51
- **Type:** Machine (ID: 1)
- **Organization: Engineering (ID: 4)**
- **Description:** Regression test credential for credential-first migration
- **Inputs:** `['password', 'username', 'become_method']` (values are encrypted)

#### 39. ServiceNow Production
- **Source ID:** 18
- **Type:** ServiceNow (ID: 34)
- **Organization: IT Operations (ID: 6)**
- **Description:** ServiceNow production instance
- **Inputs:** `['snow_instance', 'snow_password', 'snow_username']` (values are encrypted)

#### 40. Slack Notifications
- **Source ID:** 16
- **Type:** Notification Webhook (ID: 32)
- **Organization: DevOps Platform (ID: 9)**
- **Description:** Slack webhook for job notifications
- **Inputs:** `['channel', 'webhook_url', 'webhook_type']` (values are encrypted)

#### 41. Vault-Backed AWS Credential
- **Source ID:** 23
- **Type:** Amazon Web Services (ID: 5)
- **Organization: Cloud Services (ID: 8)**
- **Description:** AWS credentials dynamically retrieved from HashiCorp Vault
- **Inputs:** `[]` (values are encrypted)

#### 42. Vault-Backed SSH Credential
- **Source ID:** 22
- **Type:** Machine (ID: 1)
- **Organization: IT Operations (ID: 6)**
- **Description:** SSH credential with secrets pulled from HashiCorp Vault
- **Inputs:** `['username']` (values are encrypted)

---

## Next Steps

1. Review missing credentials above
2. Run migration to create missing credentials
3. Note: Secret values will need manual entry (API returns `$encrypted$`)
