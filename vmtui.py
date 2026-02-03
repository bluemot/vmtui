#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
vmtui.py - Unified KVM Manager (Restored Features Edition)

Combines modern features (Windows/Registry) with classic reliability (Zombie Fix, Hibernate, Console).

Features:
1.  **Multi-OS**: Linux (Cloud-Init) & Windows (ISO).
2.  **Registry**: Tracks VMs via 'vms.json'.
3.  **Classic Ops**: Console, Hibernate (Disk), Suspend (RAM), Force Stop.
4.  **Zombie Fix**: Detects and cleans defined-but-missing VMs.
5.  **Logging**: Serial logging to file (ttyS1 for Linux).

Usage: sudo python3 vmtui.py
"""

import curses
import os
import sys
import subprocess
import time
import shutil
import json
import re
import urllib.request
import urllib.error
import pwd
import grp

# --- Configuration ---

SUDO_USER = os.environ.get('SUDO_USER')
if SUDO_USER:
    USER_HOME = os.path.expanduser(f"~{SUDO_USER}")
else:
    USER_HOME = os.path.expanduser("~")

CONFIG_FILE = "vmtui.json"
VM_REGISTRY_FILE = "vms.json"

# Default directories
DEFAULT_LINUX_DIR = os.path.abspath("vms")
DEFAULT_WINDOWS_DIR = os.path.abspath("win_vms")
HOST_SHARE_DIR = os.path.join(USER_HOME, "driver_projects")

# Global State
VM_REGISTRY = {} # { "vm_name": "/path/to/vm_dir" }
CURRENT_VM = ""

# Linux Cloud Images
LINUX_IMAGES = {
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

# Windows Specifics
VIRTIO_URL = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"
COMMON_ISO_DIR = os.path.join(DEFAULT_WINDOWS_DIR, "iso")

# --- Config & Registry Management ---

def load_config():
    global VM_REGISTRY
    if os.path.exists(VM_REGISTRY_FILE):
        try:
            with open(VM_REGISTRY_FILE, 'r') as f:
                VM_REGISTRY = json.load(f)
        except Exception:
            VM_REGISTRY = {}
    if not VM_REGISTRY:
        scan_and_register(DEFAULT_LINUX_DIR)
        scan_and_register(DEFAULT_WINDOWS_DIR)

def scan_and_register(base_dir):
    if os.path.exists(base_dir):
        for d in os.listdir(base_dir):
            p = os.path.join(base_dir, d)
            if os.path.isdir(p) and d not in VM_REGISTRY:
                if os.path.exists(os.path.join(p, f"{d}.qcow2")):
                    VM_REGISTRY[d] = p
        save_registry()

def save_registry():
    try:
        with open(VM_REGISTRY_FILE, 'w') as f:
            json.dump(VM_REGISTRY, f, indent=4)
    except Exception: pass

def get_vm_dir(vm_name):
    return VM_REGISTRY.get(vm_name)

def get_virtio_iso_path():
    return os.path.join(COMMON_ISO_DIR, "virtio-win.iso")

# --- System Helpers ---

def run_cmd(cmd, shell=False, check=True):
    try:
        if shell and isinstance(cmd, list):
            cmd = " ".join(cmd)
        result = subprocess.run(
            cmd, shell=shell, check=check, 
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return result.stdout.strip()
    except Exception: return None

def run_cmd_live(stdscr, cmd, title="Executing..."):
    h, w = stdscr.getmaxyx()
    win = curses.newwin(h - 4, w - 4, 2, 2)
    win.scrollok(True)
    win.idlok(True)
    stdscr.clear()
    draw_header(stdscr)
    stdscr.addstr(2, 2, f" {title} ", curses.A_BOLD | curses.A_REVERSE)
    stdscr.refresh()
    
    output_buffer = []
    error_buffer = []

    try:
        process = subprocess.Popen(
            cmd, shell=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        while True:
            retcode = process.poll()
            line = process.stdout.readline()
            if line:
                output_buffer.append(line)
                try: win.addstr(line); win.refresh()
                except curses.error: pass
            if retcode is not None:
                rest_out = process.stdout.read()
                if rest_out: win.addstr(rest_out)
                break
        
        if retcode == 0: return True, None
        else: return False, "".join(error_buffer)
    except Exception as e: return False, str(e)

def check_system_health(stdscr):
    res = subprocess.run(["systemctl", "is-active", "libvirtd"], stdout=subprocess.PIPE, text=True)
    if res.stdout.strip() != "active":
        run_cmd_live(stdscr, ["systemctl", "start", "libvirtd"], title="Starting Libvirt...")
        time.sleep(2)
    net_state = run_cmd("virsh -c qemu:///system net-info default | grep Active", shell=True, check=False)
    if not net_state or "yes" not in net_state:
        run_cmd("virsh -c qemu:///system net-start default", shell=True, check=False)
        run_cmd("virsh -c qemu:///system net-autostart default", shell=True, check=False)
    return None

def fix_permissions(stdscr, paths):
    if shutil.which("setfacl") is None:
        run_cmd_live(stdscr, ["apt", "install", "-y", "acl"], title="Installing ACL tools...")
    qemu_user = "libvirt-qemu"
    run_cmd(["setfacl", "-m", f"u:{qemu_user}:x", USER_HOME], check=False)
    for path in paths:
        if path and os.path.exists(path):
            if os.path.isdir(path):
                 run_cmd(["setfacl", "-R", "-m", f"u:{qemu_user}:rx", path], check=False)
            else:
                 run_cmd(["setfacl", "-m", f"u:{qemu_user}:r", path], check=False)
                 parent = os.path.dirname(path)
                 run_cmd(["setfacl", "-m", f"u:{qemu_user}:x", parent], check=False)

def download_with_progress(stdscr, url, filename):
    try:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
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
                        bar = "=" * int((box_w - 12) * percent)
                        stdscr.addstr(box_y, box_x, " Downloading... ")
                        stdscr.addstr(box_y + 2, box_x, f"[{bar}] {int(percent*100)}%")
                        stdscr.refresh()
        return True
    except Exception: return False

# --- UI Helpers ---

def draw_header(stdscr):
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
    stdscr.move(0, 0)
    stdscr.clrtoeol()
    header = f" VMTUI (Restored) | Active VM: {CURRENT_VM} "
    stdscr.addstr(0, 0, header)
    
    state = "Stopped"
    if CURRENT_VM:
        res = run_cmd(f"virsh -c qemu:///system domstate {CURRENT_VM}", shell=True, check=False)
        if res: state = res.strip()
    
    status = f" Status: [{state}] "
    if len(header) + len(status) < w:
        stdscr.addstr(0, w - len(status) - 1, status)
    stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)

def msg_box(stdscr, msg, title="Message"):
    h, w = stdscr.getmaxyx()
    lines = msg.split('\n')
    max_len = max([len(l) for l in lines]) if lines else 0
    box_w = min(w - 4, max(40, max_len + 6))
    
    wrapped = []
    for l in lines:
        while len(l) > box_w - 4:
            wrapped.append(l[:box_w-4])
            l = l[box_w-4:]
        wrapped.append(l)
    
    box_h = len(wrapped) + 4
    win = curses.newwin(box_h, box_w, h//2 - box_h//2, w//2 - box_w//2)
    win.box()
    win.addstr(0, 2, f" {title} ", curses.A_BOLD)
    for i, l in enumerate(wrapped):
        if i < box_h - 2: win.addstr(i + 2, 3, l)
    win.addstr(box_h - 1, box_w - 10, "[ OK ]", curses.A_REVERSE)
    win.refresh()
    win.getch()

def input_box(stdscr, prompt, default=""):
    curses.echo()
    h, w = stdscr.getmaxyx()
    stdscr.addstr(h-3, 2, " " * (w-4))
    stdscr.addstr(h-3, 2, prompt)
    stdscr.addstr(h-3, len(prompt)+3, default, curses.A_DIM)
    inp = stdscr.getstr(h-3, len(prompt)+3, 60).decode('utf-8').strip()
    curses.noecho()
    return inp if inp else default

def selection_menu(stdscr, title, items):
    curses.curs_set(0)
    current_row = 0
    stdscr.timeout(1000) # Auto-refresh for status
    while True:
        stdscr.clear()
        draw_header(stdscr)
        h, w = stdscr.getmaxyx()
        stdscr.addstr(2, 2, title, curses.A_UNDERLINE | curses.A_BOLD)
        
        max_display = h - 6
        start = max(0, current_row - max_display + 1) if current_row >= max_display else 0
        
        for i, item in enumerate(items[start:start+max_display]):
            idx = start + i
            if idx == current_row:
                stdscr.addstr(4+i, 4, f" {item} ", curses.A_REVERSE)
            else:
                stdscr.addstr(4+i, 4, f" {item} ")
        
        key = stdscr.getch()
        if key == curses.KEY_UP and current_row > 0: current_row -= 1
        elif key == curses.KEY_DOWN and current_row < len(items) - 1: current_row += 1
        elif key == ord('\n'): return current_row
        elif key == ord('q') or key == 27: return -1
        elif key == -1: continue

def file_browser(stdscr, start_path):
    current_path = os.path.abspath(start_path)
    if not os.path.exists(current_path): current_path = USER_HOME
    while True:
        try:
            entries = sorted(os.listdir(current_path))
            dirs = [d for d in entries if os.path.isdir(os.path.join(current_path, d))]
            files = [f for f in entries if f.lower().endswith('.iso') or f.lower().endswith('.img')]
            items = [".. (Go Up)"] + [f"/{d}" for d in dirs] + files
            idx = selection_menu(stdscr, f"Select ISO: {current_path}", items)
            if idx == -1: return None
            sel = items[idx]
            if sel == ".. (Go Up)": current_path = os.path.dirname(current_path)
            elif sel.startswith("/"): current_path = os.path.join(current_path, sel[1:])
            else: return os.path.join(current_path, sel)
        except: return None

def usb_menu_logic(stdscr):
    if not CURRENT_VM:
        msg_box(stdscr, "No Active VM selected.")
        return
    curses.curs_set(0)
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
                if f"vendor id='0x{d['vid']}'" in xml and f"product id='0x{d['pid']}'" in xml:
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
        elif key == ord('q') or key == 27: 
            stdscr.timeout(-1)
            break
        elif key == ord('\n'):
            sel_display, sel_dev, sel_attached = menu_items[current_row]
            if sel_dev is None: continue
            action = "detach-device" if sel_attached else "attach-device"
            xml_content = f"<hostdev mode='subsystem' type='usb' managed='yes'><source><vendor id='0x{sel_dev['vid']}'/><product id='0x{sel_dev['pid']}'/></source></hostdev>"
            xml_path = "/tmp/vmtui_usb.xml"
            with open(xml_path, "w") as f: f.write(xml_content)
            run_cmd(["virsh", action, CURRENT_VM, xml_path, "--live"], check=False)
            time.sleep(0.5)
        elif key == -1: continue

# --- Logic: Host Setup ---

def setup_host(stdscr):
    pkgs = [
        "qemu-kvm", "libvirt-daemon-system", "libvirt-clients", "virtinst", 
        "virt-viewer", "swtpm", "swtpm-tools", "acl", "ovmf", 
        "cloud-image-utils", "virtiofsd", "unzip", "wireless-tools"
    ]
    if selection_menu(stdscr, "Install/Update KVM packages?", ["No", "Yes"]) == 1:
        run_cmd_live(stdscr, ["apt", "update"], title="Updating apt...")
        run_cmd_live(stdscr, ["apt", "install", "-y"] + pkgs, title="Installing KVM Tools...")
    
    check_system_health(stdscr)
    if SUDO_USER:
        run_cmd(f"usermod -aG libvirt,kvm {SUDO_USER}", shell=True, check=False)
    msg_box(stdscr, "Host Setup Complete.\nPlease reboot if you just installed these for the first time.")

# --- Logic: Create VM ---

def get_host_interfaces():
    interfaces = []
    try:
        result = subprocess.run(['ip', '-o', 'link', 'show'], stdout=subprocess.PIPE, text=True)
        for line in result.stdout.split('\n'):
            parts = line.split(': ')
            if len(parts) >= 2:
                iface = parts[1].strip()
                if iface != 'lo' and not iface.startswith('virbr') and not iface.startswith('docker') and 'state UP' in line:
                    interfaces.append(iface)
    except Exception: pass
    return interfaces

def select_network_config(stdscr):
    args = ["--network", "network=default,model=virtio"]
    choice = selection_menu(stdscr, "Network Configuration", [
        "NAT (Default) - Host isolated, simple",
        "Bridge - LAN accessible",
        "Dual (NAT + Bridge) - Recommended for Servers"
    ])
    if choice == 1:
        ifaces = get_host_interfaces()
        if ifaces:
            idx = selection_menu(stdscr, "Select Interface to Bridge", ifaces)
            if idx != -1: args = ["--network", f"type=direct,source={ifaces[idx]},source_mode=bridge,model=virtio"]
    elif choice == 2:
        ifaces = get_host_interfaces()
        if ifaces:
            idx = selection_menu(stdscr, "Select Interface for NIC #2", ifaces)
            if idx != -1: args = ["--network", "network=default,model=virtio", "--network", f"type=direct,source={ifaces[idx]},source_mode=bridge,model=virtio"]
    return args

def create_vm_wizard(stdscr):
    global CURRENT_VM, VM_REGISTRY
    if check_system_health(stdscr): return

    name = input_box(stdscr, "VM Name: ", "my-vm")
    if not name: return

    # --- Zombie / Overwrite Logic (Restored) ---
    dom_info = run_cmd(f"virsh -c qemu:///system dominfo {name}", shell=True, check=False)
    is_zombie = (dom_info is not None and "Id:" in dom_info)
    
    # Check Registry & Filesystem
    in_registry = name in VM_REGISTRY
    vm_dir_guess = os.path.join(DEFAULT_LINUX_DIR, name) 
    dir_exists = os.path.exists(vm_dir_guess)
    
    if is_zombie or in_registry or dir_exists:
        msg = f"WARNING: VM '{name}' exists!"
        if is_zombie: msg += " (Active in Libvirt)"
        if in_registry: msg += " (In Registry)"
        if dir_exists: msg += " (Directory found)"
        
        choice = selection_menu(stdscr, msg, ["Cancel", "Overwrite (Delete Old & Recreate)"])
        if choice == 0 or choice == -1: return
        
        # Cleanup
        run_cmd(f"virsh -c qemu:///system destroy {name}", shell=True, check=False)
        run_cmd(f"virsh -c qemu:///system undefine {name} --nvram", shell=True, check=False)
        if dir_exists:
            try: shutil.rmtree(vm_dir_guess)
            except: pass
        if in_registry:
            del VM_REGISTRY[name]
            save_registry()

    os_type = selection_menu(stdscr, "Select Operating System", [
        "Windows 10 / 11 (ISO Install)",
        "Linux Cloud Image (Auto-Install)"
    ])
    
    default_base = DEFAULT_WINDOWS_DIR if os_type == 0 else DEFAULT_LINUX_DIR
    vm_dir = os.path.join(default_base, name)
    
    # Custom Path
    custom = input_box(stdscr, "Customize Path? (Empty for default)", "")
    if custom: vm_dir = os.path.join(os.path.abspath(custom), name)

    os.makedirs(vm_dir, exist_ok=True)
    if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {vm_dir}", shell=True)

    disk_path = os.path.join(vm_dir, f"{name}.qcow2")
    disk_size = input_box(stdscr, "Disk Size (e.g. 64G, 128G): ", "64G")
    net_args = select_network_config(stdscr)

    if os_type == 0:
        iso_start = os.path.join(USER_HOME, "Downloads")
        iso = file_browser(stdscr, iso_start)
        if not iso: return
        run_cmd_live(stdscr, ["qemu-img", "create", "-f", "qcow2", disk_path, disk_size], title="Creating Disk...")
        if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {disk_path}", shell=True)
        create_windows_vm(stdscr, name, vm_dir, disk_path, iso, net_args)
    else:
        img_names = list(LINUX_IMAGES.keys())
        idx = selection_menu(stdscr, "Select Linux Distro", img_names)
        if idx == -1: return
        img_data = LINUX_IMAGES[img_names[idx]]
        create_linux_vm_cloud(stdscr, name, vm_dir, disk_path, disk_size, img_data, net_args)

    VM_REGISTRY[name] = vm_dir
    save_registry()
    CURRENT_VM = name

def create_windows_vm(stdscr, name, vm_dir, disk_path, iso, net_args):
    virtio_iso = get_virtio_iso_path()
    if not os.path.exists(virtio_iso):
        if selection_menu(stdscr, "VirtIO Drivers missing. Download?", ["No", "Yes"]) == 1:
            download_with_progress(stdscr, VIRTIO_URL, virtio_iso)
    
    fix_permissions(stdscr, [iso, virtio_iso, disk_path, vm_dir])
    
    cmd = [
        "virt-install", "--connect", "qemu:///system",
        f"--name={name}", "--machine", "q35",
        f"--memory=8192", "--vcpus=4",
        f"--cdrom={iso}",
        f"--disk=path={disk_path},device=disk,bus=virtio,format=qcow2",
        f"--disk=path={virtio_iso},device=cdrom",
        "--os-variant=win10",
        "--graphics", "spice,listen=127.0.0.1", "--video", "qxl",
        "--channel", "spicevmc",
        "--cpu", "host-passthrough",
        "--boot", "uefi,menu=on",
        "--features", "smm=on",
        "--tpm", "backend.type=emulator,backend.version=2.0,model=tpm-tis",
        "--noautoconsole"
    ] + net_args

    success, err = run_cmd_live(stdscr, cmd, title="Installing Windows VM...")
    if success: launch_viewer(name)
    else: msg_box(stdscr, f"Failed:\n{err}")

def create_linux_vm_cloud(stdscr, name, vm_dir, disk_path, disk_size, img_data, net_args):
    cache_dir = os.path.join(DEFAULT_LINUX_DIR, "base_images")
    os.makedirs(cache_dir, exist_ok=True)
    base_img = os.path.join(cache_dir, img_data['file'])
    
    if not os.path.exists(base_img):
        if not download_with_progress(stdscr, img_data['url'], base_img):
            msg_box(stdscr, "Download Failed")
            return

    run_cmd(["qemu-img", "create", "-f", "qcow2", "-F", "qcow2", "-b", base_img, disk_path, disk_size])
    if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {disk_path}", shell=True)

    if not os.path.exists(HOST_SHARE_DIR):
        os.makedirs(HOST_SHARE_DIR, exist_ok=True)
        if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {HOST_SHARE_DIR}", shell=True)

    user_data_path = os.path.join(vm_dir, "user-data")
    meta_data_path = os.path.join(vm_dir, "meta-data")
    seed_iso_path = os.path.join(vm_dir, "seed.iso")
    log_path = os.path.join(vm_dir, f"{name}-console.log")

    user_data = f"""#cloud-config
hostname: {name}
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
  - sed -i 's/GRUB_CMDLINE_LINUX_DEFAULT=".*"/GRUB_CMDLINE_LINUX_DEFAULT="console=tty1 console=ttyS0 console=ttyS1 net.ifnames=0 biosdevname=0"/' /etc/default/grub
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
  - unzip
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

power_state:
  mode: reboot
  message: "Setup complete, rebooting..."
  condition: True
"""
    with open(user_data_path, "w") as f: f.write(user_data)
    with open(meta_data_path, "w") as f: f.write(f"instance-id: {name}\nlocal-hostname: {name}\n")
    if os.path.exists(seed_iso_path): os.remove(seed_iso_path)
    run_cmd(["cloud-localds", seed_iso_path, user_data_path, meta_data_path])
    
    fix_permissions(stdscr, [disk_path, seed_iso_path, vm_dir])

    cmd = [
        "virt-install", "--connect", "qemu:///system",
        f"--name={name}", "--memory=4096", "--vcpus=2",
        "--memorybacking", "source.type=memfd,access.mode=shared",
        f"--disk=path={disk_path},device=disk,bus=virtio",
        f"--disk=path={seed_iso_path},device=cdrom",
        f"--os-variant={img_data['variant']}",
        "--import",
        "--graphics", "spice,listen=127.0.0.1", "--video", "qxl",
        "--channel", "spicevmc",
        "--serial", "pty", 
        "--serial", f"file,path={log_path}",
        "--console", "pty,target_type=serial",
        f"--filesystem", f"source={HOST_SHARE_DIR},target=host_share,driver.type=virtiofs,accessmode=passthrough",
        "--cpu", "host-passthrough",
        "--noautoconsole"
    ] + net_args

    success, err = run_cmd_live(stdscr, cmd, title=f"Installing {name}...")
    
    if success:
        try:
            qemu_uid = pwd.getpwnam('libvirt-qemu').pw_uid
            kvm_gid = grp.getgrnam('kvm').gr_gid
            if os.path.exists(log_path): os.chown(log_path, qemu_uid, kvm_gid)
        except: pass
        msg_box(stdscr, f"VM {name} Created.\nAuto-rebooting in 30s...\nLogin: ubuntu / password")
    else:
        msg_box(stdscr, f"Error:\n{err}")

# --- Logic: Management ---

def launch_viewer(vm_name):
    cmd = ["virt-viewer", "--connect", "qemu:///system", "--attach", vm_name]
    if SUDO_USER:
        cmd = ["sudo", "-E", "-u", SUDO_USER] + cmd
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def start_vm(stdscr):
    if not CURRENT_VM:
        msg_box(stdscr, "No Active VM selected.")
        return
    state = run_cmd(f"virsh -c qemu:///system domstate {CURRENT_VM}", shell=True, check=False)
    if state and "running" in state:
        launch_viewer(CURRENT_VM)
        return
    success, err = run_cmd_live(stdscr, ["virsh", "-c", "qemu:///system", "start", CURRENT_VM], title="Starting...")
    if success: launch_viewer(CURRENT_VM)
    else: msg_box(stdscr, f"Error starting VM:\n{err}")

def delete_vm(stdscr):
    if not CURRENT_VM: return
    if selection_menu(stdscr, f"DELETE VM '{CURRENT_VM}' & ALL FILES?", ["No", "Yes, Delete"]) != 1: return
    run_cmd(f"virsh -c qemu:///system destroy {CURRENT_VM}", shell=True, check=False)
    run_cmd(f"virsh -c qemu:///system undefine {CURRENT_VM} --nvram", shell=True, check=False)
    path = get_vm_dir(CURRENT_VM)
    if path and os.path.exists(path):
        try: shutil.rmtree(path)
        except: pass
    if CURRENT_VM in VM_REGISTRY:
        del VM_REGISTRY[CURRENT_VM]
        save_registry()
    msg_box(stdscr, f"VM '{CURRENT_VM}' deleted.")

def import_vm_logic(stdscr):
    global CURRENT_VM, VM_REGISTRY
    path = input_box(stdscr, "Path to existing VM directory: ", os.getcwd())
    if not path or not os.path.isdir(path): return
    path = os.path.abspath(path)
    name = os.path.basename(path)
    name = input_box(stdscr, "VM Name: ", name)
    VM_REGISTRY[name] = path
    save_registry()
    CURRENT_VM = name
    msg_box(stdscr, f"Imported '{name}'.")

def switch_vm_menu(stdscr):
    global CURRENT_VM
    vms = sorted(list(VM_REGISTRY.keys()))
    if not vms:
        msg_box(stdscr, "No VMs found. Create or Import one.")
        return
    idx = selection_menu(stdscr, "Select Active VM", vms + ["Cancel"])
    if idx != -1 and idx < len(vms):
        CURRENT_VM = vms[idx]

# --- Main ---

def main(stdscr):
    load_config()
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)
    
    if os.geteuid() != 0:
        msg_box(stdscr, "Warning: Not running as root. Some features may fail.")

    while True:
        menu_opts = [
            "1. Setup Host Environment",
            "2. Create New VM (Linux / Windows)",
            "3. Switch Active VM",
            "4. Console (Text Access) [Linux Only]",
            "5. Start / Restore (from Disk)",
            "6. Viewer (Graphical Access)",
            "7. USB Manager",
            "8. Hibernate (Save to Disk)",
            "9. Pause (Freeze in RAM)",
            "A. Resume (Unfreeze RAM)",
            "B. Force Stop VM",
            "C. Delete Active VM",
            "D. Import / Rescue VM Directory",
            "Q. Quit"
        ]
        
        idx = selection_menu(stdscr, "Main Menu", menu_opts)
        
        if idx == 0: setup_host(stdscr)
        elif idx == 1: create_vm_wizard(stdscr)
        elif idx == 2: switch_vm_menu(stdscr)
        elif idx == 3:
            curses.endwin()
            os.system(f"virsh -c qemu:///system console {CURRENT_VM}")
        elif idx == 4: start_vm(stdscr)
        elif idx == 5: launch_viewer(CURRENT_VM)
        elif idx == 6: usb_menu_logic(stdscr)
        elif idx == 7:
             msg_box(stdscr, "Hibernating...")
             run_cmd(["virsh", "-c", "qemu:///system", "managedsave", CURRENT_VM], check=False)
        elif idx == 8: run_cmd(["virsh", "-c", "qemu:///system", "suspend", CURRENT_VM], check=False)
        elif idx == 9: run_cmd(["virsh", "-c", "qemu:///system", "resume", CURRENT_VM], check=False)
        elif idx == 10: run_cmd(["virsh", "-c", "qemu:///system", "destroy", CURRENT_VM], check=False)
        elif idx == 11: delete_vm(stdscr)
        elif idx == 12: import_vm_logic(stdscr)
        elif idx == 13 or idx == -1: break

if __name__ == "__main__":
    if os.geteuid() != 0:
        args = ["sudo", "-E", sys.executable] + sys.argv
        os.execvp("sudo", args)
    try:
        curses.wrapper(main)
    except Exception as e:
        print(f"Critical Error: {e}")
