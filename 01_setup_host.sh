#!/bin/bash
# ------------------------------------------------------------------
# Script Name: 01_setup_host.sh
# Description: Installs KVM, libvirt, and cloud-utils on the Host.
#              Configures user permissions.
# ------------------------------------------------------------------

set -e

echo "[INFO] Updating package list..."
sudo apt update

echo "[INFO] Installing KVM, Libvirt, and virtualization tools..."
# cloud-image-utils is needed to generate the configuration ISO (cloud-init)
sudo apt install -y qemu-kvm libvirt-daemon-system libvirt-clients bridge-utils virtinst cloud-image-utils
sudo apt install -y virtiofsd
echo "[INFO] Adding current user to libvirt and kvm groups..."
sudo usermod -aG libvirt $USER
sudo usermod -aG kvm $USER

echo "[INFO] Setup complete."
echo "[WARN] You MUST log out and log back in (or reboot) for group permissions to take effect."
echo "[WARN] Please reboot before running the next script."
