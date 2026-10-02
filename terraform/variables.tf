# Oracle Cloud credentials
variable "tenancy_ocid"       { type = string }
variable "user_ocid"          { type = string }
variable "fingerprint"        { type = string }
variable "private_key_path"   { type = string, default = "~/.oci/oci_api_key.pem" }
variable "region"             { type = string, default = "ap-mumbai-1" }
variable "compartment_ocid"   { type = string }

# Server configuration
variable "ssh_public_key"     { type = string }
variable "domain_name"        { type = string, description = "Your domain, e.g. yourname.duckdns.org" }
variable "letsencrypt_email"  { type = string }
variable "github_repo_url"    { type = string, description = "GitHub repo containing the finance app" }
variable "admin_password"     { type = string, sensitive = true, description = "Initial admin password" }