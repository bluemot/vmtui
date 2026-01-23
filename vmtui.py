#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
vmtui.py - KVM Manager (Final Version)

Features:
1. TUI Interface (Curses) with Auto-Refresh.
2. SSH Password Login Enabled (via cloud-init).
3. Shared Folder: Host HOME (~/) -> Guest /home/ubuntu/host_share.
4. Pre-installed Packages: bear, net-tools, libnss-libvirt.
5. Console Logging to File (ttyS1) for debugging crashes.
6. Suspend (RAM) & Hibernate (Disk) Support.
7. USB Hotplug Manager.
8. Native Progress Bar for Downloads (urllib).
9. Real-time Output Window for long-running commands (apt).

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

# --- Configuration ---

# Determine the SUDO user to map home directories correctly
SUDO_USER = os.environ.get('SUDO_USER')
if SUDO_USER:
    USER_HOME = os.path.expanduser(f"~{SUDO_USER}")
else:
    USER_HOME = os.path.expanduser("~")

HOST_SHARE_DIR = os.path.join(USER_HOME, "driver_projects")
RAM_SIZE = 4096
VCPUS = 4
DISK_SIZE = "20G"

# Global State: The name of the VM we are currently managing
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

def run_cmd(cmd, shell=False, check=True):
    """
    Executes a shell command in the background and returns stdout.
    Used for quick/silent commands (e.g., virsh domstate).
    """
    try:
        # shell=True requires cmd to be a string
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
    """
    Executes a command and streams its output to a scrolling Curses window.
    Used for long-running tasks like 'apt install' so the user sees progress.
    """
    h, w = stdscr.getmaxyx()
    
    # Create a window for output
    win = curses.newwin(h - 4, w - 4, 2, 2)
    win.scrollok(True) # Enable scrolling
    win.idlok(True)
    
    # Draw simple border/title
    stdscr.clear()
    draw_header(stdscr)
    stdscr.addstr(2, 2, f" {title} ", curses.A_BOLD | curses.A_REVERSE)
    stdscr.refresh()
    
    try:
        # Use Popen to capture stdout in real-time
        process = subprocess.Popen(
            cmd, 
            shell=False, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.STDOUT, # Merge stderr into stdout
            text=True, 
            bufsize=1
        )
        
        while True:
            # Read line by line
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                try:
                    win.addstr(line)
                    win.refresh()
                except curses.error:
                    pass # Ignore errors if line is too long or window is full
                    
        return process.poll() == 0

    except Exception as e:
        win.addstr(f"\n[Error] Failed to execute: {e}")
        win.refresh()
        time.sleep(2)
        return False

def download_with_progress(stdscr, url, filename):
    """
    Downloads a file using urllib with a visual progress bar in Curses.
    Replaces 'wget' to avoid terminal buffer issues.
    """
    try:
        h, w = stdscr.getmaxyx()
        
        # UI Setup for Progress Box
        box_w = min(60, w - 4)
        box_x = (w - box_w) // 2
        box_y = h // 2 - 2
        
        # Open connection
        with urllib.request.urlopen(url) as response:
            total_size = int(response.info().get('Content-Length', 0))
            block_size = 8192
            downloaded = 0
            
            with open(filename, 'wb') as f:
                while True:
                    buffer = response.read(block_size)
                    if not buffer:
                        break
                    
                    downloaded += len(buffer)
                    f.write(buffer)
                    
                    # --- Draw Progress Bar ---
                    if total_size > 0:
                        percent = downloaded / total_size
                        bar_len = box_w - 12 # Reserve space for text
                        filled_len = int(bar_len * percent)
                        bar = "=" * filled_len + "-" * (bar_len - filled_len)
                        
                        # Draw Title
                        stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
                        stdscr.addstr(box_y, box_x, f" Downloading Image... {url} ")
                        stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
                        
                        # Draw Bar: [====----] 45%
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
    if os.geteuid() != 0:
        print("Error: Must run as root (sudo python3 vmtui.py)")
        sys.exit(1)

# --- Logic Functions ---

def setup_host_logic(stdscr):
    """
    Installs KVM, Libvirt, and necessary tools on the Host machine.
    Uses 'run_cmd_live' so user can see apt-get output.
    """
    run_cmd_live(stdscr, ["apt", "update"], title="apt update...")
    
    pkgs = [
        "qemu-kvm", 
        "libvirt-daemon-system", 
        "libvirt-clients", 
        "bridge-utils", 
        "virtinst", 
        "cloud-image-utils", 
        "virtiofsd",
        "libnss-libvirt" # For hostname resolution
    ]
    
    # Use Live Output window for installation
    success = run_cmd_live(stdscr, ["apt", "install", "-y"] + pkgs, title="Installing Packages...")
    
    if success:
        if SUDO_USER:
            run_cmd(["usermod", "-aG", "libvirt", SUDO_USER], check=False)
            run_cmd(["usermod", "-aG", "kvm", SUDO_USER], check=False)
        msg_box(stdscr, "Host Setup Complete.\nNote: Check /etc/nsswitch.conf for 'libvirt'.\nPlease REBOOT for permissions to take effect.")
    else:
        msg_box(stdscr, "Host Setup Failed. Check internet connection.")

def create_vm_logic(stdscr, img_name, img_data):
    """
    Provisioning logic: Download image, Create Disk, Gen Cloud-init, Install VM.
    """
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    disk_path = f"{CURRENT_VM}.qcow2"
    
    def log(msg, y):
        stdscr.move(y, 0)
        stdscr.clrtoeol()
        stdscr.addstr(y, 2, f"> {msg}")
        stdscr.refresh()

    log(f"Preparing {CURRENT_VM} with {img_name}...", 2)

    # 1. Setup Shared Directory (Host Side)
    if not os.path.exists(HOST_SHARE_DIR):
        os.makedirs(HOST_SHARE_DIR, exist_ok=True)
        if SUDO_USER:
            run_cmd(f"chown -R {SUDO_USER}:{SUDO_USER} {HOST_SHARE_DIR}", shell=True)

    # 2. Download Image (Using Native Curses Progress Bar)
    if not os.path.exists(img_data['file']):
        # Clear screen for the progress bar
        stdscr.clear()
        success = download_with_progress(stdscr, img_data['url'], img_data['file'])
        
        # Redraw background after download
        stdscr.clear()
        draw_header(stdscr)
        log(f"Preparing {CURRENT_VM} with {img_name}...", 2)
        
        if not success:
            return # Abort if download failed

    # 3. Create Disk
    log("Creating Disk (QCOW2)...", 4)
    if os.path.exists(disk_path): os.remove(disk_path)
    run_cmd(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", img_data['file'], disk_path, DISK_SIZE])
    if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {disk_path}", shell=True)

    # 4. Generate Cloud-Init Config
    log("Generating Cloud-Init Configuration...", 5)
    
    # Cloud-init: SSH Fix + Multi-Console + Mount Point + Packages
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
  
  # Create mount point in Guest's home directory
  - mkdir -p /home/ubuntu/host_share
  - chown ubuntu:ubuntu /home/ubuntu/host_share
  # Auto-mount Host directory via virtiofs
  - echo "host_share /home/ubuntu/host_share virtiofs defaults 0 0" >> /etc/fstab
  - mount -a

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
"""
    with open("user-data", "w") as f: f.write(user_data)
    with open("meta-data", "w") as f: f.write(f"instance-id: {CURRENT_VM}\nlocal-hostname: {CURRENT_VM}\n")
    if os.path.exists("seed.iso"): os.remove("seed.iso")
    run_cmd(["cloud-localds", "seed.iso", "user-data", "meta-data"])

    # 5. Clean Old Instance
    log("Destroying old instance...", 6)
    run_cmd(f"virsh destroy {CURRENT_VM}", shell=True, check=False)
    run_cmd(f"virsh undefine {CURRENT_VM}", shell=True, check=False)

    # 6. Install VM
    log("Launching VM via virt-install...", 7)
    
    # Log path set to /var/log/libvirt/qemu to comply with AppArmor
    log_path = f"/var/log/libvirt/qemu/{CURRENT_VM}-console.log"
    
    install_cmd = [
        "virt-install",
        f"--name={CURRENT_VM}", f"--memory={RAM_SIZE}",
        "--memorybacking", "source.type=memfd,access.mode=shared",
        f"--vcpus={VCPUS}",
        f"--disk=path={disk_path},device=disk,bus=virtio",
        "--disk=path=seed.iso,device=cdrom",
        f"--os-variant={img_data['variant']}",
        "--import", "--graphics", "none",
        
        # --- 修改重點開始 ---
        # 1. 第一個 Serial (serial0): 指定為 PTY (這就是給 virsh console 用的)
        "--serial", "pty", 
        # 2. 第二個 Serial (serial1): 指定為 File (這是給 Log 用的)
        "--serial", f"file,path={log_path}",
        # 3. 指定 Console 連接到第一個 Serial
        "--console", "pty,target_type=serial",
        # --- 修改重點結束 ---
        
        f"--filesystem", f"source={HOST_SHARE_DIR},target=host_share,driver.type=virtiofs,accessmode=passthrough",
        "--cpu", "host-passthrough",
        "--network", "network=default,model=virtio",
        "--noautoconsole"
    ]
    success = run_cmd_live(stdscr, install_cmd, title="Installing VM (Please Watch for Errors)")
    
    if success:
        if os.path.exists(log_path):
            try:
                qemu_uid = pwd.getpwnam('libvirt-qemu').pw_uid
                kvm_gid = grp.getgrnam('kvm').gr_gid
                os.chown(log_path, qemu_uid, kvm_gid)
                os.chmod(log_path, 0o640)
            except KeyError:
                pass
            except Exception as e:
                pass
        # --------------------------------

# --- UI Components ---

def draw_header(stdscr):
    h, w = stdscr.getmaxyx()
    
    # 1. Background Bar
    # Use color pair 4 (Header) to fill the line
    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
    stdscr.move(0, 0)
    stdscr.clrtoeol()
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
    """Displays a simple message box and waits for a key press."""
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
    """Generic vertical menu with 1-second auto-refresh for status updates."""
    curses.curs_set(0)
    current_row = 0
    stdscr.timeout(1000) # Refresh every 1000ms
    
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
        
        stdscr.addstr(h-2, 2, "Use Arrow Keys to Select, ENTER to Confirm, 'q' to Back")
        stdscr.refresh()
        
        key = stdscr.getch()
        
        if key == curses.KEY_UP and current_row > 0: current_row -= 1
        elif key == curses.KEY_DOWN and current_row < len(items) - 1: current_row += 1
        elif key == ord('\n'): return current_row
        elif key == ord('q') or key == 27: return -1
        elif key == -1: continue

def usb_menu_logic(stdscr):
    """USB Manager with Auto-Refresh logic."""
    current_row = 0
    stdscr.timeout(2000) # Refresh device list every 2s
    
    while True:
        # 1. Scan (Inside loop for auto-refresh)
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
        stdscr.addstr(2, 2, "USB Device Manager (Auto-Refresh)", curses.A_BOLD | curses.A_UNDERLINE)
        
        for i, item in enumerate(menu_items):
            display_str, _, is_attached = item
            y = 4 + i
            
            # Base Color
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
            xml_path = "/tmp/vmtui_usb.xml"
            with open(xml_path, "w") as f: f.write(xml_content)
            
            run_cmd(["virsh", action, CURRENT_VM, xml_path, "--live"], check=False)
            time.sleep(0.5)

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
    # Colors: 1=White, 2=Green, 3=Red, 4=WhiteOnBlue(Header)
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
        "5. Start / Restore (from Disk)",  # Maps to virsh start
        "6. Hibernate (Save to Disk)",     # Maps to virsh managedsave
        "7. Pause (Freeze in RAM)",        # Maps to virsh suspend
        "8. Resume (Unfreeze RAM)",        # Maps to virsh resume
        "9. Force Stop VM",
        "A. Switch Active VM",
        "Q. Quit"
    ]

    while True:
        idx = selection_menu(stdscr, "Main Menu", menu_options)
        stdscr.timeout(-1) # Reset to blocking mode for actions

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
            
        elif idx == 4: # Start / Restore
            run_cmd(["virsh", "start", CURRENT_VM], check=False)
            
        elif idx == 5: # Hibernate
            msg_box(stdscr, "Hibernating to disk (managedsave)...\nHost can be rebooted safely.")
            run_cmd(["virsh", "managedsave", CURRENT_VM], check=False)
            
        elif idx == 6: # Pause (RAM)
            # This is the real virsh suspend
            run_cmd(["virsh", "suspend", CURRENT_VM], check=False)
            
        elif idx == 7: # Resume (RAM)
            # This is the real virsh resume (unfreezes suspend)
            run_cmd(["virsh", "resume", CURRENT_VM], check=False)
            
        elif idx == 8: # Force Stop
            run_cmd(["virsh", "destroy", CURRENT_VM], check=False)
            
        elif idx == 9: # Switch VM
            new_vm = input_box(stdscr, "Enter VM Name: ")
            if new_vm: CURRENT_VM = new_vm
            
        elif idx == 10 or idx == -1: # Quit
            break

if __name__ == "__main__":
    check_root()
    curses.wrapper(main)