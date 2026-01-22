#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
vmtui.py - Curses-based KVM Manager (Final Fixed Version)

Features:
1. Auto-refreshing Status (Non-blocking UI).
2. Safe Header Drawing (Prevents wrap glitches).
3. SSH Password Login Fix included.
4. USB Hotplug Manager.
"""

import curses
import os
import sys
import subprocess
import time
import re

# --- Configuration ---
SUDO_USER = os.environ.get('SUDO_USER')
if SUDO_USER:
    USER_HOME = os.path.expanduser(f"~{SUDO_USER}")
else:
    USER_HOME = os.path.expanduser("~")

HOST_SHARE_DIR = os.path.join(USER_HOME, "driver_projects")
RAM_SIZE = 4096
VCPUS = 4
DISK_SIZE = "20G"

# Global State
CURRENT_VM = "driver-dev-vm"

# Images
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
def run_cmd(cmd, shell=False, check=True):
    try:
        # shell=True requires cmd to be a string
        if shell and isinstance(cmd, list):
            cmd = " ".join(cmd)
            
        result = subprocess.run(
            cmd, shell=shell, check=check, 
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None
    except Exception:
        return None

def check_root():
    if os.geteuid() != 0:
        print("Error: Must run as root (sudo python3 vmtui.py)")
        sys.exit(1)

# --- Logic Functions ---

def setup_host_logic(stdscr):
    stdscr.clear()
    stdscr.addstr(2, 2, "Installing KVM tools... Please wait.")
    stdscr.refresh()
    run_cmd(["apt", "update"], check=False)
    pkgs = ["qemu-kvm", "libvirt-daemon-system", "libvirt-clients", "bridge-utils", "virtinst", "cloud-image-utils", "virtiofsd"]
    run_cmd(["apt", "install", "-y"] + pkgs, check=False)
    if SUDO_USER:
        run_cmd(["usermod", "-aG", "libvirt", SUDO_USER], check=False)
        run_cmd(["usermod", "-aG", "kvm", SUDO_USER], check=False)
    
    msg_box(stdscr, "Host Setup Complete.\nPlease REBOOT for permissions to take effect.")

def create_vm_logic(stdscr, img_name, img_data):
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    disk_path = f"{CURRENT_VM}.qcow2"
    
    def log(msg, y):
        # Clear line first
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.addstr(y, 2, f"> {msg}")
        stdscr.refresh()

    log(f"Preparing {CURRENT_VM} with {img_name}...", 2)

    # 1. Setup Dir
    if not os.path.exists(HOST_SHARE_DIR):
        os.makedirs(HOST_SHARE_DIR, exist_ok=True)
        if SUDO_USER:
            run_cmd(f"chown -R {SUDO_USER}:{SUDO_USER} {HOST_SHARE_DIR}", shell=True)

    # 2. Download
    if not os.path.exists(img_data['file']):
        log("Downloading Image (this may take time)...", 3)
        run_cmd(["wget", "-O", img_data['file'], img_data['url']], check=False)
    
    # 3. Create Disk
    log("Creating Disk...", 4)
    if os.path.exists(disk_path): os.remove(disk_path)
    run_cmd(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", img_data['file'], disk_path, DISK_SIZE])
    if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {disk_path}", shell=True)

    # 4. Cloud Init (Fixed for SSH)
    log("Generating Config...", 5)
    # Added ssh_pwauth: true
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
  - sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=".*"/GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0 net.ifnames=0 biosdevname=0"/' /etc/default/grub
  - update-grub
  - mkdir -p /home/ubuntu/host_share
  - chown ubuntu:ubuntu /home/ubuntu/host_share
  - echo "host_share /home/ubuntu/host_share virtiofs defaults 0 0" >> /etc/fstab
  - mount -a
packages:
  - build-essential
  - linux-headers-generic
  - bear
  - net-tools
  - nfs-common
"""
    with open("user-data", "w") as f: f.write(user_data)
    with open("meta-data", "w") as f: f.write(f"instance-id: {CURRENT_VM}\nlocal-hostname: {CURRENT_VM}\n")
    if os.path.exists("seed.iso"): os.remove("seed.iso")
    run_cmd(["cloud-localds", "seed.iso", "user-data", "meta-data"])

    # 5. Clean & Install
    log("Destroying old instance...", 6)
    run_cmd(f"virsh destroy {CURRENT_VM}", shell=True, check=False)
    run_cmd(f"virsh undefine {CURRENT_VM}", shell=True, check=False)

    log("Launching VM...", 7)
    install_cmd = [
        "virt-install",
        f"--name={CURRENT_VM}", f"--memory={RAM_SIZE}",
        "--memorybacking", "source.type=memfd,access.mode=shared",
        f"--vcpus={VCPUS}",
        f"--disk=path={disk_path},device=disk,bus=virtio",
        "--disk=path=seed.iso,device=cdrom",
        f"--os-variant={img_data['variant']}",
        "--import", "--graphics", "none",
        "--console", "pty,target_type=serial",
        f"--filesystem", f"source={HOST_SHARE_DIR},target=host_share,driver.type=virtiofs,accessmode=passthrough",
        "--cpu", "host-passthrough",
        "--network", "network=default,model=virtio",
        "--noautoconsole"
    ]
    run_cmd(install_cmd, check=False)
    msg_box(stdscr, f"VM {CURRENT_VM} Created Successfully!\nWait 30s for boot, then connect.")

# --- UI Components ---

def draw_header(stdscr):
    h, w = stdscr.getmaxyx()
    
    # 1. Background Bar
    # Use color pair 4 (Header) to fill the line
    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
    stdscr.move(0, 0)
    stdscr.clrtoeol() # Clear line with current color background
    # Manually fill spaces to be safe against clrtoeol behavior on some terms
    stdscr.addstr(0, 0, " " * (w - 1)) 
    
    # 2. Left Text
    header_text = f" VMTUI | VM: {CURRENT_VM} "
    stdscr.addstr(0, 0, header_text)

    # 3. Right Status (The logic that was broken)
    # Get Status
    state = run_cmd(f"virsh domstate {CURRENT_VM}", shell=True, check=False)
    if not state: state = "Not Found"
    
    status_text = f" Status: [{state.upper()}] "
    
    # Calculate position: width - length - 2 (Safe margin)
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
    # Blocking wait
    c = win.getch()

def selection_menu(stdscr, title, items):
    """Generic vertical selection menu with Auto-Refresh"""
    curses.curs_set(0)
    current_row = 0
    stdscr.timeout(1000) # Refresh every 1000ms (1 sec) if no input
    
    while True:
        stdscr.clear()
        draw_header(stdscr) # Updates status every second
        
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
        
        stdscr.addstr(h-2, 2, "Use Arrow Keys to Select, ENTER to Confirm, 'q' to Back")
        stdscr.refresh()
        
        key = stdscr.getch()
        
        if key == curses.KEY_UP and current_row > 0:
            current_row -= 1
        elif key == curses.KEY_DOWN and current_row < len(items) - 1:
            current_row += 1
        elif key == ord('\n'):
            return current_row
        elif key == ord('q') or key == 27: # Esc
            return -1
        elif key == -1:
            # Timeout occurred, loop repeats and redraws header
            continue

def usb_menu_logic(stdscr):
    """USB Menu with Auto-Refresh"""
    current_row = 0
    stdscr.timeout(2000) # Refresh USB list every 2s
    
    while True:
        # 1. Scan (Inside loop for auto-refresh)
        devices = []
        lsusb = run_cmd(["lsusb"])
        if lsusb:
            for line in lsusb.split('\n'):
                m = re.search(r"Bus (\d+) Device (\d+): ID ([0-9a-fA-F]+):([0-9a-fA-F]+) (.+)", line)
                if m:
                    devices.append({'vid': m.group(3), 'pid': m.group(4), 'name': m.group(5)})
        
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

        if not menu_items:
            menu_items.append(("No USB Devices Found", None, False))

        if current_row >= len(menu_items):
            current_row = max(0, len(menu_items) - 1)

        # Render
        stdscr.clear()
        draw_header(stdscr)
        stdscr.addstr(2, 2, "USB Device Manager (Auto-Refresh)", curses.A_BOLD | curses.A_UNDERLINE)
        
        for i, item in enumerate(menu_items):
            display_str, _, is_attached = item
            y = 4 + i
            
            # Base Color
            attr = curses.color_pair(2) if is_attached else curses.color_pair(1)
            # Merge Highlight
            if i == current_row:
                attr |= curses.A_REVERSE
            
            stdscr.addstr(y, 4, display_str, attr)

        stdscr.addstr(stdscr.getmaxyx()[0]-2, 2, "ENTER to Toggle, 'q' to Back")
        stdscr.refresh()

        key = stdscr.getch()

        if key == curses.KEY_UP and current_row > 0:
            current_row -= 1
        elif key == curses.KEY_DOWN and current_row < len(menu_items) - 1:
            current_row += 1
        elif key == ord('q') or key == 27:
            break
        elif key == ord('\n'):
            sel_display, sel_dev, sel_attached = menu_items[current_row]
            if sel_dev is None: continue

            action = "detach-device" if sel_attached else "attach-device"
            msg = "Detaching..." if sel_attached else "Attaching..."
            
            stdscr.addstr(stdscr.getmaxyx()[0]-3, 2, msg, curses.color_pair(3))
            stdscr.refresh()
            
            xml_content = f"<hostdev mode='subsystem' type='usb' managed='yes'><source><vendor id='0x{sel_dev['vid']}'/><product id='0x{sel_dev['pid']}'/></source></hostdev>"
            xml_path = "/tmp/vmtui_usb.xml"
            with open(xml_path, "w") as f: f.write(xml_content)
            
            run_cmd(["virsh", action, CURRENT_VM, xml_path, "--live"], check=False)
            time.sleep(0.5) # Short wait
            # Loop continues and will refresh state

def input_box(stdscr, prompt):
    curses.echo()
    stdscr.addstr(stdscr.getmaxyx()[0]-3, 2, prompt)
    stdscr.refresh()
    # Turn off timeout for input
    stdscr.timeout(-1)
    inp = stdscr.getstr(stdscr.getmaxyx()[0]-3, len(prompt)+3, 20)
    curses.noecho()
    return inp.decode('utf-8')

# --- Main ---
def main(stdscr):
    # Setup Colors
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1) 
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE) # Changed to White on Blue for better visibility

    global CURRENT_VM

    menu_options = [
        "1. Setup Host Environment",
        "2. Create / Reset VM",
        "3. USB Manager",
        "4. Console (Access VM)",
        "5. Start VM",
        "6. Force Stop VM",
        "7. Switch Active VM",
        "8. Quit"
    ]

    while True:
        idx = selection_menu(stdscr, "Main Menu", menu_options)
        
        # Reset timeout to blocking for actions
        stdscr.timeout(-1)

        if idx == 0: # Setup
            setup_host_logic(stdscr)
        
        elif idx == 1: # Create
            img_names = list(IMAGES.keys())
            img_idx = selection_menu(stdscr, "Select OS Image", img_names)
            if img_idx != -1:
                sel_img = img_names[img_idx]
                create_vm_logic(stdscr, sel_img, IMAGES[sel_img])
        
        elif idx == 2: # USB
            usb_menu_logic(stdscr)
        
        elif idx == 3: # Console
            curses.endwin()
            os.system(f"virsh console {CURRENT_VM}")
        
        elif idx == 4: # Start
            run_cmd(["virsh", "start", CURRENT_VM], check=False)
            
        elif idx == 5: # Stop
            run_cmd(["virsh", "destroy", CURRENT_VM], check=False)
            
        elif idx == 6: # Switch
            new_vm = input_box(stdscr, "Enter VM Name: ")
            if new_vm: CURRENT_VM = new_vm
            
        elif idx == 7 or idx == -1: # Quit
            break

if __name__ == "__main__":
    check_root()
    curses.wrapper(main)