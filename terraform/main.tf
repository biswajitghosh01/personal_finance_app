# Availability domains
data "oci_identity_availability_domains" "ads" {
  compartment_id = var.tenancy_ocid
}

# Latest Ubuntu 22.04 image
data "oci_core_images" "ubuntu" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "22.04"
  shape                    = "VM.Standard.E2.1.Micro"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

# VCN
resource "oci_core_vcn" "finance" {
  compartment_id = var.compartment_ocid
  cidr_block     = "10.0.0.0/16"
  display_name   = "finance-vcn"
  dns_label      = "financevcn"
}

# Internet Gateway
resource "oci_core_internet_gateway" "finance" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.finance.id
  display_name   = "finance-igw"
  enabled        = true
}

# Route Table
resource "oci_core_route_table" "finance" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.finance.id
  display_name   = "finance-rt"
  route_rules {
    destination       = "0.0.0.0/0"
    destination_type  = "CIDR_BLOCK"
    network_entity_id = oci_core_internet_gateway.finance.id
  }
}

# Security List — only SSH, HTTP, HTTPS
resource "oci_core_security_list" "finance" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.finance.id
  display_name   = "finance-sl"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  # SSH
  ingress_security_rules {
    protocol  = "6"
    source    = "0.0.0.0/0"
    tcp_options { min = 22 max = 22 }
  }

  # HTTP (needed for Let's Encrypt HTTP-01)
  ingress_security_rules {
    protocol  = "6"
    source    = "0.0.0.0/0"
    tcp_options { min = 80 max = 80 }
  }

  # HTTPS
  ingress_security_rules {
    protocol  = "6"
    source    = "0.0.0.0/0"
    tcp_options { min = 443 max = 443 }
  }
}

# Public Subnet
resource "oci_core_subnet" "finance" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.finance.id
  cidr_block        = "10.0.1.0/24"
  display_name      = "finance-subnet"
  dns_label         = "financesubnet"
  route_table_id    = oci_core_route_table.finance.id
  security_list_ids = [oci_core_security_list.finance.id]
}

# Cloud-init user data
locals {
  cloud_init = templatefile("${path.module}/cloud-init.yaml.tpl", {
    github_repo_url   = var.github_repo_url
    domain_name       = var.domain_name
    letsencrypt_email = var.letsencrypt_email
    admin_password    = var.admin_password
  })
}

# Compute Instance (Always Free — AMD Micro)
resource "oci_core_instance" "finance" {
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  compartment_id      = var.compartment_ocid
  display_name        = "finance-server"
  shape               = "VM.Standard.E2.1.Micro"

  source_details {
    source_type = "image"
    source_id   = data.oci_core_images.ubuntu.images[0].id
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.finance.id
    assign_public_ip = true
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = base64encode(local.cloud_init)
  }
}

output "public_ip" {
  value = oci_core_instance.finance.public_ip
}