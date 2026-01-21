#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
vmtui.py - KVM/QEMU Driver Development Environment Manager (v2)

Features:
1. Host Environment Setup
2. Multi-VM Management (Create, Switch, Delete)
3. Image Selection (Ubuntu 24.04/22.04, Debian)
4. USB Device Passthrough
5. Console Access

Author: Jules (AI Assistant)
"""

import os
import sys
import subprocess
import time
import re
import glob

# --- Global State ---
# The currently active VM name (defaults to driver-dev-vm)
CURRENT_VM = "driver-dev-vm"

# --- Configuration Helpers ---
SUDO_USER = os.environ.get('SUDO_USER')
if SUDO_USER:
    USER_HOME = os.path.expanduser(f"~{SUDO_USER}")
else:
    USER_HOME = os.path.expanduser("~")

HOST_SHARE_DIR = os.path.join(USER_HOME, "driver_projects")
RAM_SIZE = 4096
VCPUS = 4

# Available Images Map
IMAGES = {
    "1": {
        "name": "Ubuntu 24.04 LTS (Noble)",
        "url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        "filename": "ubuntu-24.04-server.img",
        "variant": "ubuntu24.04"
    },
    "2": {
        "name": "Ubuntu 22.04 LTS (Jammy)",
        "url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "filename": "ubuntu-22.04-server.img",
        "variant": "ubuntu22.04"
    },
    "3": {
        "name": "Debian 12 (Bookworm)",
        "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2",
        "filename": "debian-12-generic.qcow2",
        "variant": "debian12"
    }
}

# ANSI Colors
C_RESET = "\033[0m"
C_RED = "\033[91m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_CYAN = "\033[96m"

def print_header():
    os.system('clear')
    print(f"{C_CYAN}============================================================{C_RESET}")
    print(f"{C_CYAN}   VMTUI - Driver Dev Manager v2 {C_RESET}")
    print(f"{C_CYAN}============================================================{C_RESET}")
    print(f"User: {SUDO_USER if SUDO_USER else 'root'}")
    print(f"Active VM: {C_GREEN}{CURRENT_VM}{C_RESET}")
    print(f"Shared Dir: {HOST_SHARE_DIR}")
    print("------------------------------------------------------------\n")

def check_root():
    if os.geteuid() != 0:
        print(f"{C_RED}[ERROR] This script must be run as root (sudo).{C_RESET}")
        sys.exit(1)

def run_cmd(cmd, shell=False, check=True):
    try:
        result = subprocess.run(
            cmd, shell=shell, check=check, 
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"{C_RED}[CMD ERROR] {e}{C_RESET}")
        print(f"{C_RED}STDERR: {e.stderr}{C_RESET}")
        return None

# --- Feature 1: Host Setup ---
def setup_host_env():
    print(f"{C_YELLOW}[INFO] Setting up Host Environment...{C_RESET}")
    print("1. Updating apt cache...")
    run_cmd(["apt", "update"], check=False)
    
    print("2. Installing tools...")
    pkgs = ["qemu-kvm", "libvirt-daemon-system", "libvirt-clients", "bridge-utils", "virtinst", "cloud-image-utils", "virtiofsd"]
    run_cmd(["apt", "install", "-y"] + pkgs)
    
    if SUDO_USER:
        print(f"3. Configuring user '{SUDO_USER}'...")
        run_cmd(["usermod", "-aG", "libvirt", SUDO_USER])
        run_cmd(["usermod", "-aG", "kvm", SUDO_USER])
        print(f"{C_RED}[IMPORTANT] Please REBOOT for permissions to take effect!{C_RESET}")
    input("\nPress Enter to return...")

# --- Feature 2: VM Management ---

def select_image_menu():
    print(f"{C_YELLOW}Select OS Image:{C_RESET}")
    for key, img in IMAGES.items():
        print(f" {key}. {img['name']}")
    print(" C. Custom URL")
    
    choice = input("Choice [1]: ").strip().upper()
    if not choice: choice = "1"
    
    if choice in IMAGES:
        return IMAGES[choice]
    elif choice == 'C':
        url = input("Enter Image URL: ").strip()
        name = input("Enter Local Filename (e.g. custom.img): ").strip()
        return {"name": "Custom", "url": url, "filename": name, "variant": "generic"}
    return IMAGES["1"]

def create_vm():
    global CURRENT_VM
    print_header()
    print(f"{C_YELLOW}--- Create / Reset VM ---{C_RESET}")
    
    # 1. Input Name
    new_name = input(f"Enter VM Name [default: {CURRENT_VM}]: ").strip()
    if new_name:
        CURRENT_VM = new_name
    
    # 2. Select Image
    img_config = select_image_menu()
    
    # 3. Confirmation
    print(f"\n{C_RED}WARNING: This will DELETE any existing VM named '{CURRENT_VM}'!{C_RESET}")
    if input("Continue? (y/N): ").lower() != 'y':
        return

    # --- Execution ---
    
    # Setup Dirs
    if not os.path.exists(HOST_SHARE_DIR):
        os.makedirs(HOST_SHARE_DIR, exist_ok=True)
        if SUDO_USER:
            run_cmd(f"chown -R {SUDO_USER}:{SUDO_USER} {HOST_SHARE_DIR}", shell=True)

    # Download Image
    if not os.path.exists(img_config['filename']):
        print(f"Downloading {img_config['name']}...")
        run_cmd(["wget", "-O", img_config['filename'], img_config['url']])
    else:
        print(f"Using cached image: {img_config['filename']}")

    # Prepare Disk
    disk_path = f"{CURRENT_VM}.qcow2"
    if os.path.exists(disk_path):
        os.remove(disk_path)
    
    print("Creating Disk...")
    run_cmd(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", img_config['filename'], disk_path, DISK_SIZE])
    if SUDO_USER:
        run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {disk_path}", shell=True)

    # Cloud-Init
    print("Generating Cloud-Init config...")
    user_data = f"""#cloud-config
hostname: {CURRENT_VM}
manage_etc_hosts: true
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: users, admin
    shell: /bin/bash
    lock_passwd: false
chpasswd:
  list: |
    ubuntu:password
  expire: False
runcmd:
  - sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=".*"/GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0"/' /etc/default/grub
  - update-grub
  - mkdir -p /mnt/host_share
  - echo "host_share /mnt/host_share virtiofs defaults 0 0" >> /etc/fstab
  - mount -a
packages:
  - build-essential
  - linux-headers-generic
"""
    # Note: linux-headers-generic might fail on non-ubuntu, but cloud-init usually ignores package errors
    
    with open("user-data", "w") as f: f.write(user_data)
    with open("meta-data", "w") as f: f.write(f"instance-id: {CURRENT_VM}\nlocal-hostname: {CURRENT_VM}\n")
    
    if os.path.exists("seed.iso"): os.remove("seed.iso")
    run_cmd(["cloud-localds", "seed.iso", "user-data", "meta-data"])

    # Clean old
    run_cmd(f"virsh destroy {CURRENT_VM}", shell=True, check=False)
    run_cmd(f"virsh undefine {CURRENT_VM}", shell=True, check=False)

    # Install
    print(f"{C_GREEN}Launching VM...{C_RESET}")
    install_cmd = [
        "virt-install",
        f"--name={CURRENT_VM}",
        f"--memory={RAM_SIZE}",
        "--memorybacking", "source.type=memfd,access.mode=shared",
        f"--vcpus={VCPUS}",
        f"--disk=path={disk_path},device=disk,bus=virtio",
        "--disk=path=seed.iso,device=cdrom",
        f"--os-variant={img_config['variant']}",
        "--import", "--graphics", "none",
        "--console", "pty,target_type=serial",
        f"--filesystem", f"source={HOST_SHARE_DIR},target=host_share,driver.type=virtiofs,accessmode=passthrough",
        "--cpu", "host-passthrough",
        "--network", "network=default,model=virtio",
        "--noautoconsole"
    ]
    run_cmd(install_cmd)
    
    print(f"{C_GREEN}VM '{CURRENT_VM}' created!{C_RESET}")
    input("Press Enter to return...")

def switch_vm():
    global CURRENT_VM
    print_header()
    print(f"{C_YELLOW}--- Switch Active VM ---{C_RESET}")
    
    # List all running or shut off VMs from virsh
    vms_raw = run_cmd("virsh list --all --name", shell=True, check=False)
    if not vms_raw:
        print("No VMs found.")
    else:
        vms = [v for v in vms_raw.split('\n') if v.strip()]
        for i, vm in enumerate(vms):
            print(f" {i+1}. {vm}")
        
        print("\n N. Type new name (Virtual Switch)")
        
        choice = input("\nSelect VM number or 'N': ").strip().upper()
        if choice == 'N':
            name = input("Enter VM Name: ").strip()
            if name: CURRENT_VM = name
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(vms):
                CURRENT_VM = vms[idx]
    
    input(f"Active VM set to '{CURRENT_VM}'. Press Enter...")

# --- Feature 3: USB ---
def usb_manager():
    while True:
        print_header()
        print(f"{C_YELLOW}--- USB Manager (Target: {CURRENT_VM}) ---{C_RESET}")
        
        # List Host USBs
        lsusb = run_cmd(["lsusb"])
        devices = []
        if lsusb:
            for line in lsusb.split('\n'):
                m = re.search(r"Bus (\d+) Device (\d+): ID ([0-9a-fA-F]+):([0-9a-fA-F]+) (.+)", line)
                if m:
                    devices.append({'vid': m.group(3), 'pid': m.group(4), 'name': m.group(5)})

        # Check Attached
        xml = run_cmd(["virsh", "dumpxml", CURRENT_VM], check=False)
        attached_list = []
        if xml:
            for d in devices:
                if f"id='0x{d['vid']}'" in xml and f"id='0x{d['pid']}'" in xml:
                    attached_list.append(f"{d['vid']}:{d['pid']}")

        for i, d in enumerate(devices):
            status = f"{C_GREEN}[ATTACHED]{C_RESET}" if f"{d['vid']}:{d['pid']}" in attached_list else f"{C_BLUE}[FREE]{C_RESET}"
            print(f" {i+1}. {status} {d['vid']}:{d['pid']} - {d['name']}")

        print("\n A. Attach / D. Detach / B. Back")
        choice = input("Option: ").strip().upper()
        
        if choice == 'B': break
        if choice in ['A', 'D']:
            try:
                idx = int(input("Device #: ")) - 1
                dev = devices[idx]
                xml_str = f"<hostdev mode='subsystem' type='usb' managed='yes'><source><vendor id='0x{dev['vid']}'/><product id='0x{dev['pid']}'/></source></hostdev>"
                with open("/tmp/usb.xml", "w") as f: f.write(xml_str)
                
                action = "attach-device" if choice == 'A' else "detach-device"
                run_cmd(["virsh", action, CURRENT_VM, "/tmp/usb.xml", "--live"], check=False)
                time.sleep(1)
            except: pass

# --- Main ---
def main_menu():
    global CURRENT_VM
    while True:
        print_header()
        
        # Check Status
        state = run_cmd(f"virsh domstate {CURRENT_VM}", shell=True, check=False)
        st_col = C_GREEN if state and "running" in state else C_RED
        print(f"Status: {st_col}{state if state else 'Not Found'}{C_RESET}")
        
        print("\n1. Setup Host Environment")
        print("2. Create / Reset VM (Select Image & Name)")
        print("3. USB Manager")
        print("4. Console")
        print("5. Start VM")
        print("6. Stop VM (Force)")
        print("S. Switch Active VM")
        print("Q. Quit")
        
        c = input("\nOption: ").strip().upper()
        
        if c == '1': setup_host_env()
        elif c == '2': create_vm()
        elif c == '3': usb_manager()
        elif c == '4': os.system(f"virsh console {CURRENT_VM}")
        elif c == '5': run_cmd(f"virsh start {CURRENT_VM}", shell=True, check=False); time.sleep(1)
        elif c == '6': run_cmd(f"virsh destroy {CURRENT_VM}", shell=True, check=False); time.sleep(1)
        elif c == 'S': switch_vm()
        elif c == 'Q': sys.exit(0)

if __name__ == "__main__":
    check_root()
    try: main_menu()
    except KeyboardInterrupt: sys.exit(0)
