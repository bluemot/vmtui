#!/bin/bash
# ------------------------------------------------------------------
# Script Name: 02_create_driver_vm.sh (Final Fix for Login)
# ------------------------------------------------------------------

# --- Configuration ---
VM_NAME="driver-dev-vm"
HOST_SHARE_DIR="$HOME/driver_projects"
RAM_SIZE=4096
VCPUS=4
# Ubuntu Version (Noble Numbat 24.04 LTS)
IMG_URL="https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
IMG_NAME="ubuntu-24.04-server.img"
DISK_NAME="${VM_NAME}.qcow2"
DISK_SIZE="20G"

# --- Pre-flight Checks ---

if [ ! -d "$HOST_SHARE_DIR" ]; then
    echo "[INFO] Creating shared directory: $HOST_SHARE_DIR"
    mkdir -p "$HOST_SHARE_DIR"
fi

# --- Step 1: Download Image ---
if [ ! -f "$IMG_NAME" ]; then
    echo "[INFO] Downloading Ubuntu Cloud Image..."
    wget -O "$IMG_NAME" "$IMG_URL"
else
    echo "[INFO] Image $IMG_NAME already exists. Skipping download."
fi

# --- Step 2: Create Disk ---
# Remove old disk if exists to ensure clean state
rm -f "$DISK_NAME"
echo "[INFO] Creating VM disk based on Cloud Image..."
qemu-img create -f qcow2 -F qcow2 -b "$IMG_NAME" "$DISK_NAME" $DISK_SIZE

# --- Step 3: Configure Cloud-init (User Data) ---
# FIX: Use 'chpasswd' to allow plain text password setting
cat > user-data <<EOF
#cloud-config
hostname: $VM_NAME
manage_etc_hosts: true

users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: users, admin
    shell: /bin/bash
    lock_passwd: false

# This module allows setting passwords in plain text
chpasswd:
  list: |
    ubuntu:password
  expire: False

runcmd:
  # Enable Serial Console for Kernel Debugging
  - sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=".*"/GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0"/' /etc/default/grub
  - update-grub
  # Setup VirtioFS mounting
  - mkdir -p /mnt/host_share
  - echo "host_share /mnt/host_share virtiofs defaults 0 0" >> /etc/fstab
  - mount -a

packages:
  - build-essential
  - linux-headers-generic
EOF

cat > meta-data <<EOF
instance-id: $VM_NAME
local-hostname: $VM_NAME
EOF

echo "[INFO] Generating Cloud-init ISO..."
rm -f seed.iso
cloud-localds seed.iso user-data meta-data

# --- Step 4: Install/Launch VM ---
echo "[INFO] Launching VM..."
echo "[NOTE] Login with user: 'ubuntu', password: 'password'"

# Clean up any failed previous attempts
virsh destroy "$VM_NAME" 2>/dev/null || true
virsh undefine "$VM_NAME" 2>/dev/null || true

# Launch with virtiofsd memory backing
virt-install \
  --name "$VM_NAME" \
  --memory "$RAM_SIZE" \
  --memorybacking source.type=memfd,access.mode=shared \
  --vcpus "$VCPUS" \
  --disk "path=$DISK_NAME,device=disk,bus=virtio" \
  --disk "path=seed.iso,device=cdrom" \
  --os-variant ubuntu24.04 \
  --import \
  --graphics none \
  --console pty,target_type=serial \
  --filesystem "source=$HOST_SHARE_DIR,target=host_share,driver.type=virtiofs,accessmode=passthrough" \
  --cpu host-passthrough \
  --network network=default,model=virtio

echo "[INFO] Script finished."
