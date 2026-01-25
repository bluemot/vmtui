#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
vmtui.py - KVM Manager (Anti-Zombie Edition)

Updates:
1. Zombie Fix: Detects and removes leftover VM definitions in Libvirt even if the directory is gone.
2. Self-Elevation: Auto-runs with 'sudo' if user forgets.
3. VM Isolation: All files are stored in 'vms/{VM_NAME}/'.
4. Switch VM: Auto-scan 'vms/' directory.
5. Auto-Reboot: VM reboots automatically after install.
6. Permissions: Auto-fix log file ownership.

Author: Jules (AI Assistant)
"""

import curses
import os
import sys
import subprocess
import time
import re
import urllib.request
import urllib.error
import pwd
import grp
import shutil

# --- Configuration ---

# Determine the SUDO user to map home directories correctly
SUDO_USER = os.environ.get('SUDO_USER')
if SUDO_USER:
    USER_HOME = os.path.expanduser(f"~{SUDO_USER}")
else:
    USER_HOME = os.path.expanduser("~")

# Base directory for all VM data
VM_BASE_DIR = os.path.abspath("vms")

HOST_SHARE_DIR = os.path.join(USER_HOME, "driver_projects")
RAM_SIZE = 4096
VCPUS = 4
DISK_SIZE = "20G"

# Global State
CURRENT_VM = "driver-dev-vm"

# Available OS Images
IMAGES = {
    "Ubuntu 24.04 LTS": {
        "url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        "file": "ubuntu-24.04-server.img", "variant": "ubuntu24.04"
    },
    "Ubuntu 22.04 LTS": {
        "url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "file": "ubuntu-22.04-server.img", "variant": "ubuntu22.04"
    },
    "Debian 12": {
        "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2",
        "file": "debian-12-generic.qcow2", "variant": "debian12"
    }
}

# --- Helpers ---

def get_vm_dir(vm_name):
    """Returns the absolute path to the specific VM's directory."""
    return os.path.join(VM_BASE_DIR, vm_name)

def run_cmd(cmd, shell=False, check=True):
    try:
        if shell and isinstance(cmd, list):
            cmd = " ".join(cmd)
        result = subprocess.run(
            cmd, shell=shell, check=check, 
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return result.stdout.strip()
    except Exception:
        return None

def run_cmd_live(stdscr, cmd, title="Executing..."):
    h, w = stdscr.getmaxyx()
    win = curses.newwin(h - 4, w - 4, 2, 2)
    win.scrollok(True)
    win.idlok(True)
    
    stdscr.clear()
    draw_header(stdscr)
    stdscr.addstr(2, 2, f" {title} ", curses.A_BOLD | curses.A_REVERSE)
    stdscr.refresh()
    
    try:
        process = subprocess.Popen(
            cmd, shell=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
        )
        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                try:
                    win.addstr(line)
                    win.refresh()
                except curses.error:
                    pass
        return process.poll() == 0
    except Exception as e:
        win.addstr(f"\n[Error] Failed to execute: {e}")
        win.refresh()
        time.sleep(2)
        return False

def download_with_progress(stdscr, url, filename):
    try:
        h, w = stdscr.getmaxyx()
        box_w = min(60, w - 4)
        box_x = (w - box_w) // 2
        box_y = h // 2 - 2
        
        with urllib.request.urlopen(url) as response:
            total_size = int(response.info().get('Content-Length', 0))
            block_size = 8192
            downloaded = 0
            
            with open(filename, 'wb') as f:
                while True:
                    buffer = response.read(block_size)
                    if not buffer: break
                    downloaded += len(buffer)
                    f.write(buffer)
                    
                    if total_size > 0:
                        percent = downloaded / total_size
                        bar_len = box_w - 12
                        filled_len = int(bar_len * percent)
                        bar = "=" * filled_len + "-" * (bar_len - filled_len)
                        
                        stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                        stdscr.addstr(box_y, box_x, f" Downloading Image... ")
                        stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
                        
                        stdscr.move(box_y + 2, 0)
                        stdscr.clrtoeol()
                        bar_str = f"[{bar}] {int(percent * 100)}%"
                        str_x = (w - len(bar_str)) // 2
                        stdscr.addstr(box_y + 2, str_x, bar_str, curses.color_pair(2))
                        stdscr.refresh()
        return True
    except Exception as e:
        msg_box(stdscr, f"Download Error:\n{str(e)}")
        return False

def check_root():
    """Auto-elevate to root if not already running as root."""
    if os.geteuid() != 0:
        print("Requesting root permissions (sudo)...")
        args = ["sudo", sys.executable] + sys.argv
        os.execvp("sudo", args)

# --- Logic Functions ---

def setup_host_logic(stdscr):
    run_cmd_live(stdscr, ["apt", "update"], title="apt update...")
    pkgs = ["qemu-kvm", "libvirt-daemon-system", "libvirt-clients", "bridge-utils", "virtinst", "cloud-image-utils", "virtiofsd", "libnss-libvirt"]
    success = run_cmd_live(stdscr, ["apt", "install", "-y"] + pkgs, title="Installing Packages...")
    
    if success:
        if SUDO_USER:
            run_cmd(["usermod", "-aG", "libvirt", SUDO_USER], check=False)
            run_cmd(["usermod", "-aG", "kvm", SUDO_USER], check=False)
        msg_box(stdscr, "Host Setup Complete.\nPlease REBOOT for permissions to take effect.")
    else:
        msg_box(stdscr, "Host Setup Failed.")

def create_vm_logic(stdscr, img_name, img_data):
    """
    Creates a new VM in its own directory: vms/{CURRENT_VM}/
    """
    global CURRENT_VM
    
    # 1. Ask for VM Name (Default to CURRENT_VM)
    new_name = input_box(stdscr, f"VM Name [{CURRENT_VM}]: ")
    if new_name:
        CURRENT_VM = new_name
    
    # 2. Check Overwrite (Directory OR Libvirt Domain)
    vm_dir = get_vm_dir(CURRENT_VM)
    
    # [FIX] Check if VM exists in Libvirt (Zombie check)
    dom_info = run_cmd(f"virsh dominfo {CURRENT_VM}", shell=True, check=False)
    is_zombie = (dom_info is not None and "Id:" in dom_info)
    dir_exists = os.path.exists(vm_dir)
    
    if dir_exists or is_zombie:
        msg = f"WARNING: VM '{CURRENT_VM}' already exists!"
        if is_zombie and not dir_exists:
             msg += "\n(Found in Libvirt but directory is missing)"
             
        choice = selection_menu(stdscr, msg, ["Cancel", "Overwrite (Destroy & Recreate)"])
        if choice == 0 or choice == -1:
            return # Cancel
        
        # Cleanup Logic
        run_cmd(f"virsh destroy {CURRENT_VM}", shell=True, check=False)
        run_cmd(f"virsh undefine {CURRENT_VM} --nvram", shell=True, check=False)
        if dir_exists:
            try:
                shutil.rmtree(vm_dir)
            except Exception as e:
                msg_box(stdscr, f"Error removing directory: {e}")
                return

    os.makedirs(vm_dir, exist_ok=True)
    if SUDO_USER:
        run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {vm_dir}", shell=True)

    # Define paths inside the VM dir
    disk_path = os.path.join(vm_dir, f"{CURRENT_VM}.qcow2")
    user_data_path = os.path.join(vm_dir, "user-data")
    meta_data_path = os.path.join(vm_dir, "meta-data")
    seed_iso_path = os.path.join(vm_dir, "seed.iso")
    log_path = os.path.join(vm_dir, f"{CURRENT_VM}-console.log")
    
    base_img_path = os.path.join(VM_BASE_DIR, img_data['file'])

    def log(msg, y):
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.addstr(y, 2, f"> {msg}")
        stdscr.refresh()

    stdscr.clear()
    draw_header(stdscr)
    log(f"Setting up {CURRENT_VM} in {vm_dir}...", 2)

    # 3. Setup Shared Dir
    if not os.path.exists(HOST_SHARE_DIR):
        os.makedirs(HOST_SHARE_DIR, exist_ok=True)
        if SUDO_USER:
            run_cmd(f"chown -R {SUDO_USER}:{SUDO_USER} {HOST_SHARE_DIR}", shell=True)

    # 4. Download Image (Shared Cache)
    if not os.path.exists(VM_BASE_DIR): os.makedirs(VM_BASE_DIR, exist_ok=True)
    
    if not os.path.exists(base_img_path):
        stdscr.clear()
        success = download_with_progress(stdscr, img_data['url'], base_img_path)
        stdscr.clear()
        draw_header(stdscr)
        log(f"Setting up {CURRENT_VM}...", 2)
        if not success: return

    # 5. Create Disk
    log("Creating Disk (QCOW2)...", 4)
    run_cmd(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", base_img_path, disk_path, DISK_SIZE])
    if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {disk_path}", shell=True)

    # 6. Generate Cloud-Init
    log("Generating Cloud-Init Configuration...", 5)
    
    user_data = f"""#cloud-config
hostname: {CURRENT_VM}
manage_etc_hosts: true
ssh_pwauth: true
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
  - rm -f /etc/default/grub.d/50-cloudimg-settings.cfg
  - sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=".*"/GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS1 console=ttyS0 net.ifnames=0 biosdevname=0"/' /etc/default/grub
  - update-grub
  
  - mkdir -p /home/ubuntu/host_share
  - chown ubuntu:ubuntu /home/ubuntu/host_share
  - echo "host_share /home/ubuntu/host_share virtiofs defaults 0 0" >> /etc/fstab
  - mount -a
  - systemctl enable serial-getty@ttyS0.service
  - systemctl start serial-getty@ttyS0.service

packages:
  - build-essential
  - linux-headers-generic
  - bear
  - net-tools
  - nfs-common
  - wpasupplicant
  - hostapd
  - network-manager
  - rfkill
  - iw
  - wireless-tools
  - vim
  - libnl-genl-3-dev
  - libnl-3-dev
  - libnl-route-3-dev
  - libssl-dev
  - pkgconf
  - bridge-utils
  - curl
  - samba
  - sshfs

# Auto-Reboot to apply GRUB settings
power_state:
  mode: reboot
  message: "Setup complete, rebooting..."
  condition: True
"""
    with open(user_data_path, "w") as f: f.write(user_data)
    with open(meta_data_path, "w") as f: f.write(f"instance-id: {CURRENT_VM}\nlocal-hostname: {CURRENT_VM}\n")
    if os.path.exists(seed_iso_path): os.remove(seed_iso_path)
    run_cmd(["cloud-localds", seed_iso_path, user_data_path, meta_data_path])

    # 7. Install VM
    log("Launching VM via virt-install...", 7)
    
    install_cmd = [
        "virt-install",
        f"--name={CURRENT_VM}", f"--memory={RAM_SIZE}",
        "--memorybacking", "source.type=memfd,access.mode=shared",
        f"--vcpus={VCPUS}",
        f"--disk=path={disk_path},device=disk,bus=virtio",
        "--disk=path={seed_iso_path},device=cdrom".format(seed_iso_path=seed_iso_path),
        f"--os-variant={img_data['variant']}",
        "--import",
        "--graphics", "vnc,listen=0.0.0.0,port=5900,password=123456",
        "--video", "qxl",
        "--serial", "pty", 
        "--serial", f"file,path={log_path}",
        "--console", "pty,target_type=serial",
        f"--filesystem", f"source={HOST_SHARE_DIR},target=host_share,driver.type=virtiofs,accessmode=passthrough",
        "--cpu", "host-passthrough",
        "--network", "network=default,model=virtio",
        "--noautoconsole"
    ]
    
    success = run_cmd_live(stdscr, install_cmd, title="Installing VM")
    
    if success:
        # Fix Permissions for Log file
        if os.path.exists(log_path):
            try:
                qemu_uid = pwd.getpwnam('libvirt-qemu').pw_uid
                kvm_gid = grp.getgrnam('kvm').gr_gid
                os.chown(log_path, qemu_uid, kvm_gid)
                os.chmod(log_path, 0o640)
            except: pass
            
        # Also fix ownership of the VM directory itself for the user
        if SUDO_USER:
             run_cmd(f"chown -R {SUDO_USER}:{SUDO_USER} {vm_dir}", shell=True)

        msg_box(stdscr, f"VM {CURRENT_VM} Created!\nFiles in: {vm_dir}\n\nNote: VM will auto-reboot now.\nWait 30s before connecting.")
    else:
        msg_box(stdscr, "Error: VM Installation Failed.")

def switch_vm_menu(stdscr):
    """Scans vms/ directory and lets user choose."""
    global CURRENT_VM
    
    if not os.path.exists(VM_BASE_DIR):
        os.makedirs(VM_BASE_DIR, exist_ok=True)
        
    # List subdirectories
    vms = [d for d in os.listdir(VM_BASE_DIR) if os.path.isdir(os.path.join(VM_BASE_DIR, d))]
    vms.sort()
    
    if not vms:
        msg_box(stdscr, "No VMs found in 'vms/' directory.")
        return

    # Add 'Cancel' option
    menu_items = vms + ["[ Cancel ]"]
    
    idx = selection_menu(stdscr, "Select Active VM", menu_items)
    if idx != -1 and idx < len(vms):
        CURRENT_VM = vms[idx]
        msg_box(stdscr, f"Switched to: {CURRENT_VM}")

# --- UI Components ---

def draw_header(stdscr):
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
    stdscr.move(0, 0)
    stdscr.clrtoeol()
    stdscr.addstr(0, 0, " " * (w - 1)) 
    
    header_text = f" VMTUI | VM: {CURRENT_VM} "
    stdscr.addstr(0, 0, header_text)

    state = run_cmd(f"virsh domstate {CURRENT_VM}", shell=True, check=False)
    if not state: state = "Not Found"
    status_text = f" Status: [{state.upper()}] "
    
    pos_x = w - len(status_text) - 2
    if pos_x > len(header_text):
        stdscr.addstr(0, pos_x, status_text)
    
    stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)

def msg_box(stdscr, msg):
    h, w = stdscr.getmaxyx()
    lines = msg.split('\n')
    box_h = len(lines) + 4
    box_w = max([len(l) for l in lines]) + 6
    start_y = h // 2 - box_h // 2
    start_x = w // 2 - box_w // 2
    
    win = curses.newwin(box_h, box_w, start_y, start_x)
    win.box()
    for i, line in enumerate(lines):
        win.addstr(i + 2, 3, line)
    win.addstr(box_h - 1, box_w - 10, "[ OK ]", curses.A_REVERSE)
    win.refresh()
    win.getch()

def selection_menu(stdscr, title, items):
    curses.curs_set(0)
    current_row = 0
    stdscr.timeout(1000) 
    
    while True:
        stdscr.clear()
        draw_header(stdscr)
        h, w = stdscr.getmaxyx()
        stdscr.addstr(2, 2, title, curses.A_UNDERLINE | curses.A_BOLD)
        
        for i, item in enumerate(items):
            x = 4
            y = 4 + i
            if i == current_row:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addstr(y, x, f" {item} ")
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addstr(y, x, f" {item} ")
        
        stdscr.addstr(h-2, 2, "Use Arrow Keys, ENTER to Confirm, 'q' to Back")
        stdscr.refresh()
        
        key = stdscr.getch()
        if key == curses.KEY_UP and current_row > 0: current_row -= 1
        elif key == curses.KEY_DOWN and current_row < len(items) - 1: current_row += 1
        elif key == ord('\n'): return current_row
        elif key == ord('q') or key == 27: return -1
        elif key == -1: continue

def usb_menu_logic(stdscr):
    current_row = 0
    stdscr.timeout(2000)
    
    while True:
        devices = []
        lsusb = run_cmd(["lsusb"])
        if lsusb:
            for line in lsusb.split('\n'):
                m = re.search(r"Bus (\d+) Device (\d+): ID ([0-9a-fA-F]+):([0-9a-fA-F]+) (.+)", line)
                if m: devices.append({'vid': m.group(3), 'pid': m.group(4), 'name': m.group(5)})
        
        xml = run_cmd(["virsh", "dumpxml", CURRENT_VM], check=False)
        attached_sigs = []
        if xml:
            for d in devices:
                if f"id='0x{d['vid']}'" in xml and f"id='0x{d['pid']}'" in xml:
                    attached_sigs.append(f"{d['vid']}:{d['pid']}")

        menu_items = []
        for d in devices:
            sig = f"{d['vid']}:{d['pid']}"
            is_attached = sig in attached_sigs
            status = "[ ATTACHED ]" if is_attached else "[   FREE   ]"
            display = f"{status} {sig} - {d['name'][:40]}"
            menu_items.append((display, d, is_attached))

        if not menu_items: menu_items.append(("No USB Devices Found", None, False))
        if current_row >= len(menu_items): current_row = max(0, len(menu_items) - 1)

        stdscr.clear()
        draw_header(stdscr)
        stdscr.addstr(2, 2, "USB Device Manager", curses.A_BOLD | curses.A_UNDERLINE)
        
        for i, item in enumerate(menu_items):
            display_str, _, is_attached = item
            y = 4 + i
            attr = curses.color_pair(2) if is_attached else curses.color_pair(1)
            if i == current_row: attr |= curses.A_REVERSE
            stdscr.addstr(y, 4, display_str, attr)

        stdscr.addstr(stdscr.getmaxyx()[0]-2, 2, "ENTER to Toggle, 'q' to Back")
        stdscr.refresh()

        key = stdscr.getch()
        if key == curses.KEY_UP and current_row > 0: current_row -= 1
        elif key == curses.KEY_DOWN and current_row < len(menu_items) - 1: current_row += 1
        elif key == ord('q') or key == 27: break
        elif key == ord('\n'):
            sel_display, sel_dev, sel_attached = menu_items[current_row]
            if sel_dev is None: continue

            action = "detach-device" if sel_attached else "attach-device"
            msg = "Detaching..." if sel_attached else "Attaching..."
            stdscr.addstr(stdscr.getmaxyx()[0]-3, 2, msg, curses.color_pair(3))
            stdscr.refresh()
            
            xml_content = f"<hostdev mode='subsystem' type='usb' managed='yes'><source><vendor id='0x{sel_dev['vid']}'/><product id='0x{sel_dev['pid']}'/></source></hostdev>"
            xml_path = os.path.join("/tmp", f"usb_{sel_dev['vid']}.xml")
            with open(xml_path, "w") as f: f.write(xml_content)
            run_cmd(["virsh", action, CURRENT_VM, xml_path, "--live"], check=False)
            time.sleep(0.5)

def input_box(stdscr, prompt):
    curses.echo()
    stdscr.addstr(stdscr.getmaxyx()[0]-3, 2, prompt)
    stdscr.refresh()
    stdscr.timeout(-1)
    inp = stdscr.getstr(stdscr.getmaxyx()[0]-3, len(prompt)+3, 20)
    curses.noecho()
    return inp.decode('utf-8')

# --- Main ---
def main(stdscr):
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1) 
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)

    global CURRENT_VM

    menu_options = [
        "1. Setup Host Environment",
        "2. Create / Reset VM",
        "3. USB Manager",
        "4. Console (Access VM)",
        "5. Start / Restore",
        "6. Hibernate (Save to Disk)",
        "7. Pause (Freeze in RAM)",
        "8. Resume (Unfreeze RAM)",
        "9. Force Stop VM",
        "A. Switch Active VM (Select from List)",
        "Q. Quit"
    ]

    while True:
        idx = selection_menu(stdscr, "Main Menu", menu_options)
        stdscr.timeout(-1)

        if idx == 0: setup_host_logic(stdscr)
        elif idx == 1:
            img_names = list(IMAGES.keys())
            img_idx = selection_menu(stdscr, "Select OS Image", img_names)
            if img_idx != -1:
                sel_img = img_names[img_idx]
                create_vm_logic(stdscr, sel_img, IMAGES[sel_img])
        elif idx == 2: usb_menu_logic(stdscr)
        elif idx == 3:
            curses.endwin()
            os.system(f"virsh console {CURRENT_VM}")
        elif idx == 4: run_cmd(["virsh", "start", CURRENT_VM], check=False)
        elif idx == 5:
            msg_box(stdscr, "Hibernating...")
            run_cmd(["virsh", "managedsave", CURRENT_VM], check=False)
        elif idx == 6: run_cmd(["virsh", "suspend", CURRENT_VM], check=False)
        elif idx == 7: run_cmd(["virsh", "resume", CURRENT_VM], check=False)
        elif idx == 8: run_cmd(["virsh", "destroy", CURRENT_VM], check=False)
        elif idx == 9: switch_vm_menu(stdscr)
        elif idx == 10 or idx == -1: break

if __name__ == "__main__":
    check_root()
    curses.wrapper(main)