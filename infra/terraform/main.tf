terraform {
  required_version = ">= 1.10"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.49"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------

variable "hcloud_token" {
  type        = string
  description = "Hetzner Cloud API token (write)."
  sensitive   = true
}

variable "ssh_public_key_path" {
  type        = string
  description = "Path to public SSH key uploaded to all nodes."
  default     = "~/.ssh/id_ed25519.pub"
}

variable "control_plane_location" {
  type    = string
  default = "fsn1"
}

variable "data_plane_location" {
  type    = string
  default = "hel1"
}

variable "workers_location" {
  type    = string
  default = "ash"
}

variable "control_plane_type" {
  type    = string
  default = "ccx33"
}

variable "data_plane_type" {
  type    = string
  default = "ccx53"
}

variable "workers_type" {
  type    = string
  default = "ccx43"
}

variable "image" {
  type    = string
  default = "ubuntu-24.04"
}

variable "data_volume_size_gb" {
  type    = number
  default = 1024
}

variable "cloudflare_api_token" {
  type        = string
  description = "Cloudflare API token (Tunnel + DNS)."
  sensitive   = true
  default     = ""
}

variable "cloudflare_account_id" {
  type    = string
  default = ""
}

# -----------------------------------------------------------------------------
# Providers
# -----------------------------------------------------------------------------

provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# -----------------------------------------------------------------------------
# Network
# -----------------------------------------------------------------------------

resource "hcloud_network" "vpc" {
  name     = "streaming-bot-vpc"
  ip_range = "10.0.0.0/16"
}

resource "hcloud_network_subnet" "subnet" {
  network_id   = hcloud_network.vpc.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = "10.0.1.0/24"
}

resource "hcloud_ssh_key" "operator" {
  name       = "streaming-bot-operator"
  public_key = file(var.ssh_public_key_path)
}

# -----------------------------------------------------------------------------
# Firewall
# -----------------------------------------------------------------------------

resource "hcloud_firewall" "default" {
  name = "streaming-bot-default"

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = [
      "0.0.0.0/0",
      "::/0",
    ]
    description = "SSH"
  }

  rule {
    direction = "in"
    protocol  = "udp"
    port      = "51820"
    source_ips = [
      "0.0.0.0/0",
      "::/0",
    ]
    description = "WireGuard"
  }
}

# -----------------------------------------------------------------------------
# Volumes (datos persistentes para postgres + clickhouse + minio)
# -----------------------------------------------------------------------------

resource "hcloud_volume" "data" {
  name              = "streaming-bot-data"
  size              = var.data_volume_size_gb
  location          = var.data_plane_location
  format            = "ext4"
  delete_protection = true
}

# -----------------------------------------------------------------------------
# Servers
# -----------------------------------------------------------------------------

locals {
  cloud_init = file("${path.module}/cloud-init.yaml")
}

resource "hcloud_server" "control" {
  name        = "streaming-bot-control"
  image       = var.image
  server_type = var.control_plane_type
  location    = var.control_plane_location
  ssh_keys    = [hcloud_ssh_key.operator.id]
  user_data   = local.cloud_init

  firewall_ids = [hcloud_firewall.default.id]

  network {
    network_id = hcloud_network.vpc.id
    ip         = "10.0.1.10"
  }

  labels = {
    role = "control"
    env  = "production"
  }

  depends_on = [hcloud_network_subnet.subnet]
}

resource "hcloud_server" "data" {
  name        = "streaming-bot-data"
  image       = var.image
  server_type = var.data_plane_type
  location    = var.data_plane_location
  ssh_keys    = [hcloud_ssh_key.operator.id]
  user_data   = local.cloud_init

  firewall_ids = [hcloud_firewall.default.id]

  labels = {
    role = "data"
    env  = "production"
  }
}

resource "hcloud_volume_attachment" "data_attach" {
  volume_id = hcloud_volume.data.id
  server_id = hcloud_server.data.id
  automount = true
}

resource "hcloud_server" "workers" {
  name        = "streaming-bot-workers"
  image       = var.image
  server_type = var.workers_type
  location    = var.workers_location
  ssh_keys    = [hcloud_ssh_key.operator.id]
  user_data   = local.cloud_init

  firewall_ids = [hcloud_firewall.default.id]

  labels = {
    role = "workers"
    env  = "production"
  }
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------

output "control_ip" {
  value = hcloud_server.control.ipv4_address
}

output "data_ip" {
  value = hcloud_server.data.ipv4_address
}

output "workers_ip" {
  value = hcloud_server.workers.ipv4_address
}

output "ssh_command_control" {
  value = "ssh root@${hcloud_server.control.ipv4_address}"
}

output "ssh_command_data" {
  value = "ssh root@${hcloud_server.data.ipv4_address}"
}

output "ssh_command_workers" {
  value = "ssh root@${hcloud_server.workers.ipv4_address}"
}
