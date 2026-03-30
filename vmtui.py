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
import base64

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
COMMON_ISO_DIR = os.path.join(USER_HOME, "Downloads")
HOST_SHARE_DIR = os.path.join(USER_HOME, "driver_projects")

VIRTIO_URL = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/latest-virtio/virtio-win.iso"

LINUX_IMAGES = {
    "Ubuntu 24.04 (Noble)": {
        "url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        "file": "noble-server-cloudimg-amd64.img",
        "variant": "ubuntu24.04"
    },
    "Ubuntu 22.04 (Jammy)": {
        "url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "file": "jammy-server-cloudimg-amd64.img",
        "variant": "ubuntu22.04"
    },
    "Debian 12 (Bookworm)": {
        "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2",
        "file": "debian-12-generic-amd64.qcow2",
        "variant": "debian12"
    }
}

# Global State
VM_REGISTRY = {} # { "vm_name": "/path/to/vm_dir" }
CURRENT_VM = ""

# --- Config & Registry Management ---

def load_config():
    global VM_REGISTRY, HOST_SHARE_DIR
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                conf = json.load(f)
                HOST_SHARE_DIR = conf.get("host_share_dir", HOST_SHARE_DIR)
        except Exception: pass

    if os.path.exists(VM_REGISTRY_FILE):
        try:
            with open(VM_REGISTRY_FILE, 'r') as f:
                VM_REGISTRY = json.load(f)
                # Migration: Convert old string entries to dict
                migrated = False
                for k, v in VM_REGISTRY.items():
                    if not isinstance(v, dict):
                        VM_REGISTRY[k] = {"dir": v, "host_share": HOST_SHARE_DIR}
                        migrated = True
                if migrated: save_registry()
        except Exception:
            VM_REGISTRY = {}
    if not VM_REGISTRY:
        scan_and_register(DEFAULT_LINUX_DIR)
        scan_and_register(DEFAULT_WINDOWS_DIR)

def save_config():
    try:
        with open(CONFIG_FILE, 'w') as f:
            json.dump({"host_share_dir": HOST_SHARE_DIR}, f, indent=4)
    except Exception: pass

def scan_and_register(base_dir):
    if os.path.exists(base_dir):
        for d in os.listdir(base_dir):
            p = os.path.join(base_dir, d)
            if os.path.isdir(p) and d not in VM_REGISTRY:
                if os.path.exists(os.path.join(p, f"{d}.qcow2")):
                    VM_REGISTRY[d] = {"dir": p, "host_share": HOST_SHARE_DIR}
        save_registry()

def save_registry():
    try:
        with open(VM_REGISTRY_FILE, 'w') as f:
            json.dump(VM_REGISTRY, f, indent=4)
    except Exception: pass

def get_vm_dir(vm_name):
    entry = VM_REGISTRY.get(vm_name)
    if isinstance(entry, dict):
        return entry.get("dir")
    return entry # Backward compatibility

def get_vm_share(vm_name):
    entry = VM_REGISTRY.get(vm_name)
    if isinstance(entry, dict):
        return entry.get("host_share", HOST_SHARE_DIR)
    return HOST_SHARE_DIR

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
        import queue
        q = queue.Queue()

        def read_stream(stream, is_err=False):
            for line in iter(stream.readline, ''):
                if line:
                    q.put((is_err, line))

        t1 = threading.Thread(target=read_stream, args=(process.stdout, False))
        t2 = threading.Thread(target=read_stream, args=(process.stderr, True))
        t1.start()
        t2.start()

        while process.poll() is None or not q.empty():
            try:
                is_err, line = q.get(timeout=0.1)
                if not is_err:
                    output_buffer.append(line)
                else:
                    error_buffer.append(line)
                
                if win:
                    try:
                        if is_err:
                            win.addstr(line, curses.color_pair(3))
                        else:
                            win.addstr(line)
                        win.refresh()
                    except curses.error:
                        pass
            except queue.Empty:
                pass

        t1.join()
        t2.join()
        retcode = process.returncode
        
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
        else: state = "Not Defined"
    
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
    curses.curs_set(1)
    h, w = stdscr.getmaxyx()
    
    # Box dimensions
    box_w = min(max(60, len(prompt) + 20), w - 4)
    box_h = 6
    start_y = (h - box_h) // 2
    start_x = (w - box_w) // 2
    
    win = curses.newwin(box_h, box_w, start_y, start_x)
    win.box()
    
    # Title/Prompt
    win.addstr(1, 2, prompt, curses.A_BOLD)
    
    # Default hint
    if default:
        win.addstr(3, 2, f"Default: {default}", curses.A_DIM)
        
    win.refresh()
    
    curses.echo()
    try:
        # Input field at line 2
        inp = win.getstr(2, 2, box_w - 4).decode('utf-8').strip()
    except curses.error:
        inp = ""
        
    curses.noecho()
    curses.curs_set(0)
    
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

def file_browser(stdscr, start_path, title="Select File"):
    current_path = os.path.abspath(start_path)
    if not os.path.exists(current_path): current_path = USER_HOME
    while True:
        try:
            entries = sorted(os.listdir(current_path))
            dirs = [d for d in entries if os.path.isdir(os.path.join(current_path, d))]
            files = [f for f in entries if f.lower().endswith('.iso') or f.lower().endswith('.img') or f.lower().endswith('.qcow2')]
            items = [".. (Go Up)"] + [f"/{d}" for d in dirs] + files
            idx = selection_menu(stdscr, f"{title}: {current_path}", items)
            if idx == -1: return None
            sel = items[idx]
            if sel == ".. (Go Up)": current_path = os.path.dirname(current_path)
            elif sel.startswith("/"): current_path = os.path.join(current_path, sel[1:])
            else: return os.path.join(current_path, sel)
        except: return None

def directory_browser(stdscr, start_path, title="Select Directory"):
    current_path = os.path.abspath(start_path)
    if not os.path.exists(current_path): current_path = USER_HOME
    while True:
        try:
            entries = sorted(os.listdir(current_path))
            dirs = [d for d in entries if os.path.isdir(os.path.join(current_path, d))]
            items = [" [ SELECT CURRENT DIRECTORY ] ", ".. (Go Up)"] + [f"/{d}" for d in dirs]
            idx = selection_menu(stdscr, f"{title}: {current_path}", items)
            if idx == -1: return None
            sel = items[idx]
            if sel == " [ SELECT CURRENT DIRECTORY ] ": return current_path
            elif sel == ".. (Go Up)": current_path = os.path.dirname(current_path)
            elif sel.startswith("/"): current_path = os.path.join(current_path, sel[1:])
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

def cdrom_menu_logic(stdscr):
    if not CURRENT_VM:
        msg_box(stdscr, "No Active VM selected.")
        return
    
    while True:
        # Get list of CD-ROM devices
        # Use domblklist to find devices with type 'cdrom' or ending in 'da'/'db' that are not disks
        blk_info = run_cmd(f"virsh -c qemu:///system domblklist {CURRENT_VM} --details", shell=True, check=False)
        cdroms = []
        if blk_info:
            for line in blk_info.split('\n'):
                if "cdrom" in line or "rom" in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        target = parts[2]
                        source = parts[3] if len(parts) > 3 else "[ Empty ]"
                        cdroms.append({"target": target, "source": source})
        
        if not cdroms:
            if selection_menu(stdscr, "No CD-ROM devices found. Add one?", ["Cancel", "Add Empty CD-ROM (sda)"]) == 1:
                run_cmd(f"virsh -c qemu:///system attach-disk {CURRENT_VM} \"\" sda --type cdrom --mode readonly --config --targetbus sata", shell=True, check=False)
                continue
            return

        menu_items = [f"Device: {c['target']} | Source: {os.path.basename(c['source'])}" for c in cdroms]
        menu_items.append("Cancel")
        
        idx = selection_menu(stdscr, f"Manage CD-ROMs for {CURRENT_VM}", menu_items)
        if idx == -1 or idx == len(cdroms): break
        
        selected_cd = cdroms[idx]
        act_idx = selection_menu(stdscr, f"Action for {selected_cd['target']}", ["Insert ISO (Mount)", "Eject (Unmount)", "Back"])
        
        if act_idx == 0: # Insert
            iso_start = os.path.join(USER_HOME, "Downloads")
            iso_path = file_browser(stdscr, iso_start)
            if iso_path:
                fix_permissions(stdscr, [iso_path])
                # Check VM state to decide flags
                state = run_cmd(f"virsh -c qemu:///system domstate {CURRENT_VM}", shell=True, check=False)
                flags = ["--config"]
                if state and "running" in state:
                    flags.append("--live")
                
                cmd = ["virsh", "-c", "qemu:///system", "change-media", CURRENT_VM, selected_cd['target'], iso_path] + flags
                success, err = run_cmd_live(stdscr, cmd, title=f"Mounting {os.path.basename(iso_path)}...")
                if not success: msg_box(stdscr, f"Failed to mount:\n{err}")
        
        elif act_idx == 1: # Eject
            state = run_cmd(f"virsh -c qemu:///system domstate {CURRENT_VM}", shell=True, check=False)
            flags = ["--config"]
            if state and "running" in state:
                flags.append("--live")
                
            cmd = ["virsh", "-c", "qemu:///system", "change-media", CURRENT_VM, selected_cd['target'], "--eject"] + flags
            success, err = run_cmd_live(stdscr, cmd, title="Ejecting...")
            if not success: msg_box(stdscr, f"Failed to eject:\n{err}")
        
        elif act_idx == 2: continue

# --- Logic: Host Setup ---

def configure_nss_libvirt(stdscr):
    content = run_cmd("cat /etc/nsswitch.conf", shell=True, check=False)
    if not content:
        return False, "Could not read /etc/nsswitch.conf"
    
    lines = content.split('\n')
    new_lines = []
    changed = False
    for line in lines:
        if line.startswith('hosts:') and 'libvirt' not in line:
            # Insert libvirt before dns or append if dns not found
            if 'dns' in line:
                # Use regex to replace 'dns' with 'libvirt dns' to handle spacing
                new_line = re.sub(r'(\b)dns(\b)', r'\1libvirt dns\2', line)
            else:
                new_line = line.rstrip() + ' libvirt'
            new_lines.append(new_line)
            changed = True
        else:
            new_lines.append(line)
    
    if changed:
        new_content = '\n'.join(new_lines)
        tmp_file = "/tmp/nsswitch.conf.tmp"
        try:
            with open(tmp_file, "w") as f:
                f.write(new_content)
            run_cmd(f"cp {tmp_file} /etc/nsswitch.conf", shell=True)
            return True, None
        except Exception as e:
            return False, str(e)
    return True, None

def change_host_share_path(stdscr):
    global HOST_SHARE_DIR
    new_path = directory_browser(stdscr, HOST_SHARE_DIR, "Select Host Share Directory")
    if new_path:
        HOST_SHARE_DIR = os.path.abspath(new_path)
        try:
            os.makedirs(HOST_SHARE_DIR, exist_ok=True)
            if SUDO_USER:
                run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {HOST_SHARE_DIR}", shell=True)
        except Exception as e:
            msg_box(stdscr, f"Error: {e}")
        
        save_config()
        msg_box(stdscr, f"Shared Directory updated to:\n{HOST_SHARE_DIR}")

def setup_host(stdscr):
    while True:
        opts = [
            "1. Install/Update KVM Packages",
            f"2. Change Host Share Directory (Current: {HOST_SHARE_DIR})",
            "3. Back"
        ]
        choice = selection_menu(stdscr, "Host Setup Environment", opts)
        
        if choice == 0:
            pkgs = [
                "qemu-kvm", "libvirt-daemon-system", "libvirt-clients", "virtinst", 
                "virt-viewer", "swtpm", "swtpm-tools", "acl", "ovmf", 
                "cloud-image-utils", "unzip", "wireless-tools", "bridge-utils",
                "libnss-libvirt"
            ]
            
            # On newer Ubuntu (24.04+), virtiofsd is a separate package
            try:
                os_release = run_cmd("lsb_release -sc", shell=True, check=False)
                if os_release and os_release.strip() not in ["focal", "jammy"]:
                    pkgs.append("virtiofsd")
            except: pass

            success, err = run_cmd_live(stdscr, ["apt", "update"], title="Updating apt...")
            if not success:
                msg_box(stdscr, f"Apt update failed:\n{err}")
                continue
            
            success, err = run_cmd_live(stdscr, ["apt", "install", "-y"] + pkgs, title="Installing KVM Tools...")
            if not success:
                msg_box(stdscr, f"Package installation failed:\n{err}")
                continue

            # Configure libvirt in nsswitch.conf
            nss_success, nss_err = configure_nss_libvirt(stdscr)
            if not nss_success:
                msg_box(stdscr, f"Warning: Could not configure /etc/nsswitch.conf:\n{nss_err}")

            check_system_health(stdscr)
            if SUDO_USER:
                run_cmd(f"usermod -aG libvirt,kvm {SUDO_USER}", shell=True, check=False)
                # Apply ACL permissions for current directory
                run_cmd(f"setfacl -R -m u:{SUDO_USER}:rwX .", shell=True, check=False)
                run_cmd(f"setfacl -d -m u:{SUDO_USER}:rwX .", shell=True, check=False)
                
            msg_box(stdscr, f"Host Setup Complete.\n\nPermissions & ACLs applied for user: {SUDO_USER if SUDO_USER else 'root'}\n\nIMPORTANT: Please logout and login again (or reboot) for group membership (libvirt/kvm) to take full effect in your terminal session.")
        elif choice == 1:
            change_host_share_path(stdscr)
        else:
            break

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
    if os_type == -1: return
    
    default_base = DEFAULT_WINDOWS_DIR if os_type == 0 else DEFAULT_LINUX_DIR
    vm_dir = os.path.join(default_base, name)
    
    # Custom Path
    if selection_menu(stdscr, f"Use default path? ({vm_dir})", ["Yes, use default", "No, browse for custom path"]) == 1:
        custom = directory_browser(stdscr, default_base, "Select Base Directory for VM")
        if custom: vm_dir = os.path.join(custom, name)

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

    VM_REGISTRY[name] = {"dir": vm_dir, "host_share": HOST_SHARE_DIR}
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
        f"--disk=path={iso},device=cdrom,bus=sata,boot.order=1",
        f"--disk=path={disk_path},device=disk,bus=virtio,format=qcow2,boot.order=2",
        f"--disk=path={virtio_iso},device=cdrom,bus=sata,boot.order=3",
        "--os-variant=win10",
        "--graphics", "spice,listen=127.0.0.1", "--video", "qxl",
        "--channel", "spicevmc",
        "--cpu", "host-passthrough",
        "--boot", "uefi,menu=on",
        "--features", "smm=on",
        "--memorybacking", "source.type=memfd,access.mode=shared",
        f"--filesystem", f"source={HOST_SHARE_DIR},target=host_share,driver.type=virtiofs,accessmode=passthrough",
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
    if not state:
         msg_box(stdscr, f"VM '{CURRENT_VM}' is not defined in Libvirt.\nCannot start.")
         return
    if "running" in state:
        launch_viewer(CURRENT_VM)
        return
    success, err = run_cmd_live(stdscr, ["virsh", "-c", "qemu:///system", "start", CURRENT_VM], title="Starting...")
    if success: launch_viewer(CURRENT_VM)
    else: msg_box(stdscr, f"Error starting VM:\n{err}")

def resize_vm_disk(stdscr):
    if not CURRENT_VM:
        msg_box(stdscr, "No Active VM selected.")
        return
        
    # Get Disk Path
    blklist = run_cmd(f"virsh -c qemu:///system domblklist {CURRENT_VM} --details", shell=True, check=False)
    disk_path = None
    if blklist:
        for line in blklist.split('\n'):
            # Look for file based disks (vda/sda)
            if "disk" in line and "file" in line:
                parts = line.split()
                if len(parts) >= 4:
                    disk_path = parts[-1] # Path is usually last
                    break
    
    if not disk_path or not os.path.exists(disk_path):
        # Fallback to Registry if VM is off/undefined
        disk_path = os.path.join(get_vm_dir(CURRENT_VM), f"{CURRENT_VM}.qcow2")
        if not os.path.exists(disk_path):
             msg_box(stdscr, "Could not locate VM disk image.")
             return

    # User Input
    size = input_box(stdscr, "Expand by (e.g. +10G, +50G): ", "+10G")
    if not size or "+" not in size: return

    if selection_menu(stdscr, f"Expand '{disk_path}' by {size}?", ["Cancel", "Confirm"]) == 1:
        success, err = run_cmd_live(stdscr, ["qemu-img", "resize", disk_path, size], title="Resizing Disk...")
        if success:
            msg_box(stdscr, "Disk Expanded Successfully.\n\nIMPORTANT:\n1. Boot the VM.\n2. Open Disk Management (Windows) or 'gparted' (Linux).\n3. Extend the partition into the new unallocated space.")
        else:
            msg_box(stdscr, f"Error:\n{err}")

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

def duplicate_vm(stdscr):
    if not CURRENT_VM:
        msg_box(stdscr, "No Active VM selected to duplicate.")
        return

    src_vm = CURRENT_VM
    dst_vm = input_box(stdscr, f"Clone '{src_vm}' as New VM Name: ", f"{src_vm}-clone")
    if not dst_vm or dst_vm == src_vm: 
        return

    # Check if target VM already exists
    dom_info = run_cmd(f"virsh -c qemu:///system dominfo {dst_vm}", shell=True, check=False)
    if dom_info and "Id:" in dom_info:
        msg_box(stdscr, f"Error: VM '{dst_vm}' already exists in Libvirt.")
        return

    # Suspend source VM to ensure data consistency during clone
    state = run_cmd(f"virsh -c qemu:///system domstate {src_vm}", shell=True, check=False)
    was_running = False
    if state and "running" in state:
        if selection_menu(stdscr, f"'{src_vm}' is running. Suspend it during clone?", ["Cancel", "Suspend & Clone"]) == 1:
            run_cmd_live(stdscr, ["virsh", "-c", "qemu:///system", "suspend", src_vm], title="Suspending source VM...")
            was_running = True
        else:
            return

    # Prepare directories
    entry = VM_REGISTRY.get(src_vm)
    src_dir = entry.get("dir") if isinstance(entry, dict) else DEFAULT_LINUX_DIR
    base_dir = os.path.dirname(src_dir) if src_dir and os.path.exists(src_dir) else DEFAULT_LINUX_DIR
    
    dst_dir = os.path.join(base_dir, dst_vm)
    os.makedirs(dst_dir, exist_ok=True)
    if SUDO_USER: 
        run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {dst_dir}", shell=True)
    
    dst_disk = os.path.join(dst_dir, f"{dst_vm}.qcow2")

    # 1. Execute virt-clone
    success, err = run_cmd_live(stdscr, ["virt-clone", "--original", src_vm, "--name", dst_vm, "--file", dst_disk], title=f"Cloning Disk to {dst_vm}...")
    
    # Resume source VM if it was suspended
    if was_running:
        run_cmd(["virsh", "-c", "qemu:///system", "resume", src_vm], check=False)

    if not success:
        msg_box(stdscr, f"Clone failed:\n{err}")
        return

    # 2. Isolate host_share directory
    new_share = os.path.join(USER_HOME, f"driver_projects_{dst_vm}")
    os.makedirs(new_share, exist_ok=True)
    if SUDO_USER: 
        run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {new_share}", shell=True)
    
    update_vm_virtiofs_path(stdscr, dst_vm, new_share)
    
    # Register the new VM
    VM_REGISTRY[dst_vm] = {"dir": dst_dir, "host_share": new_share, "installing": False}
    save_registry()

    # 3. Guest Agent Injection for Linux Auto-Fix
    if selection_menu(stdscr, f"Clone Complete! Run Guest Agent Auto-Fix (Linux only)?\nThis will reset IP, Hostname, and Machine-ID.", ["No", "Yes (Start VM & Fix)"]) == 1:
        run_cmd_live(stdscr, ["virsh", "-c", "qemu:///system", "start", dst_vm], title="Starting cloned VM...")
        
        # Wait for QEMU Guest Agent to become responsive
        msg_box(stdscr, "Waiting for VM to boot and Guest Agent to start...\nPlease wait up to 30 seconds.")
        ready = False
        for _ in range(15):
            res = run_cmd(f"virsh -c qemu:///system qemu-agent-command {dst_vm} '{{\"execute\":\"guest-ping\"}}'", shell=True, check=False)
            if res and "return" in res:
                ready = True
                break
            time.sleep(2)
            
        if ready:
            # Shell script to fix Linux identity issues
            fix_script = f"""
hostnamectl set-hostname {dst_vm}
sed -i 's/{src_vm}/{dst_vm}/g' /etc/hosts
rm -f /etc/machine-id /var/lib/dbus/machine-id
systemd-machine-id-setup
ln -sf /etc/machine-id /var/lib/dbus/machine-id
sed -i '/match:/d' /etc/netplan/*.yaml 2>/dev/null
sed -i '/macaddress:/d' /etc/netplan/*.yaml 2>/dev/null
netplan apply
"""
            # Encode script to avoid escaping issues in JSON
            encoded_script = base64.b64encode(fix_script.encode('utf-8')).decode('utf-8')
            
            cmd_args = {
                "execute": "guest-exec",
                "arguments": {
                    "path": "/bin/bash",
                    "arg": ["-c", f"echo {encoded_script} | base64 -d | bash"],
                    "capture-output": True
                }
            }
            # Inject script
            run_cmd(["virsh", "-c", "qemu:///system", "qemu-agent-command", dst_vm, json.dumps(cmd_args)], check=False)
            
            # Reboot to apply machine-id changes
            reboot_args = {"execute":"guest-exec", "arguments":{"path":"/sbin/reboot"}}
            run_cmd(["virsh", "-c", "qemu:///system", "qemu-agent-command", dst_vm, json.dumps(reboot_args)], check=False)
            
            msg_box(stdscr, f"Auto-Fix applied successfully!\nVM '{dst_vm}' is rebooting with its new identity.")
        else:
            msg_box(stdscr, "Guest Agent timeout.\nThe VM took too long to boot or QGA is not installed.\nYou will need to fix Hostname/IP manually.")

def import_vm_logic(stdscr):
    global CURRENT_VM, VM_REGISTRY
    path = directory_browser(stdscr, os.getcwd(), "Select Existing VM Directory")
    if not path or not os.path.isdir(path): return
    name = os.path.basename(path)
    name = input_box(stdscr, "Confirm/Edit VM Name: ", name)
    if not name: return
    
    # Register in JSON
    VM_REGISTRY[name] = {"dir": path, "host_share": HOST_SHARE_DIR}
    save_registry()
    CURRENT_VM = name
    
    # Check Libvirt
    dom_info = run_cmd(f"virsh -c qemu:///system dominfo {name}", shell=True, check=False)
    if not dom_info or "Id:" not in dom_info:
        if selection_menu(stdscr, f"VM '{name}' not in Libvirt. Restore from disk?", ["No", "Yes"]) == 1:
            restore_vm_from_disk(stdscr, name, path)
    else:
        msg_box(stdscr, f"Imported '{name}'.")

def restore_vm_from_disk(stdscr, name, path):
    # Find Disk
    disks = [f for f in os.listdir(path) if f.endswith('.qcow2')]
    if not disks:
        msg_box(stdscr, "No .qcow2 disk found in directory.")
        return
    
    disk_path = os.path.join(path, disks[0])
    if len(disks) > 1:
        idx = selection_menu(stdscr, "Select Disk Image", disks)
        if idx == -1: return
        disk_path = os.path.join(path, disks[idx])
        
    os_type = selection_menu(stdscr, "Select OS Type for Restore", [
        "Windows 10/11 (UEFI, VirtIO)",
        "Linux (Generic VirtIO)"
    ])
    if os_type == -1: return

    mem = input_box(stdscr, "Memory (MB): ", "4096")
    cpus = input_box(stdscr, "vCPUs: ", "2")
    
    fix_permissions(stdscr, [disk_path, path])
    
    cmd = []
    if os_type == 0: # Windows
        virtio_iso = get_virtio_iso_path()
        cmd = [
            "virt-install", "--connect", "qemu:///system",
            f"--name={name}", "--machine", "q35",
            f"--memory={mem}", f"--vcpus={cpus}",
            f"--disk=path={disk_path},device=disk,bus=virtio,format=qcow2,boot.order=1",
            "--os-variant=win10",
            "--graphics", "spice,listen=127.0.0.1", "--video", "qxl",
            "--channel", "spicevmc",
            "--cpu", "host-passthrough",
            "--boot", "uefi,menu=on",
            "--features", "smm=on",
            "--memorybacking", "source.type=memfd,access.mode=shared",
            f"--filesystem", f"source={HOST_SHARE_DIR},target=host_share,driver.type=virtiofs,accessmode=passthrough",
            "--tpm", "backend.type=emulator,backend.version=2.0,model=tpm-tis",
            "--import", "--noautoconsole"
        ]
        # Attach VirtIO ISO if exists, just in case drivers are needed
        if os.path.exists(virtio_iso):
             cmd.insert(8, f"--disk=path={virtio_iso},device=cdrom,bus=sata,boot.order=2")
             
    else: # Linux
        cmd = [
            "virt-install", "--connect", "qemu:///system",
            f"--name={name}", 
            f"--memory={mem}", f"--vcpus={cpus}",
            "--memorybacking", "source.type=memfd,access.mode=shared",
            f"--disk=path={disk_path},device=disk,bus=virtio",
            "--os-variant=generic",
            "--graphics", "spice,listen=127.0.0.1", "--video", "qxl",
            "--channel", "spicevmc",
            "--console", "pty,target_type=serial",
            f"--filesystem", f"source={HOST_SHARE_DIR},target=host_share,driver.type=virtiofs,accessmode=passthrough",
            "--cpu", "host-passthrough",
            "--import", "--noautoconsole"
        ]

    success, err = run_cmd_live(stdscr, cmd, title=f"Restoring {name}...")
    if success:
        msg_box(stdscr, f"VM '{name}' restored and started!")
    else:
        msg_box(stdscr, f"Restore Failed:\n{err}")

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

def edit_vm_settings(stdscr):
    if not CURRENT_VM:
        msg_box(stdscr, "No Active VM selected.")
        return
    
    global VM_REGISTRY
    entry = VM_REGISTRY.get(CURRENT_VM)
    if not isinstance(entry, dict):
        # Convert old format to new format on the fly
        entry = {"dir": entry, "host_share": HOST_SHARE_DIR}
        VM_REGISTRY[CURRENT_VM] = entry

    current_share = entry.get("host_share", HOST_SHARE_DIR)
    
    opts = [
        f"1. Set Host Share Path (Current: {current_share})",
        "2. Manage CD-ROMs / ISOs",
        "3. Back"
    ]
    
    choice = selection_menu(stdscr, f"Settings for {CURRENT_VM}", opts)
    if choice == 0:
        new_path = directory_browser(stdscr, current_share, "Select Share Directory for THIS VM")
        if new_path:
            # Update Registry
            entry["host_share"] = new_path
            save_registry()
            
            # Update Libvirt XML if VM is defined
            dom_info = run_cmd(f"virsh -c qemu:///system dominfo {CURRENT_VM}", shell=True, check=False)
            if dom_info and "Id:" in dom_info:
                update_vm_virtiofs_path(stdscr, CURRENT_VM, new_path)
            
            msg_box(stdscr, f"Settings updated for {CURRENT_VM}")
    elif choice == 1:
        cdrom_menu_logic(stdscr)

def update_vm_virtiofs_path(stdscr, vm_name, new_path):
    # This helper updates the XML of the VM to point to the new path
    xml = run_cmd(f"virsh -c qemu:///system dumpxml {vm_name}", shell=True, check=False)
    if xml and "virtiofs" in xml:
        # Use a temporary python script to modify the path in XML
        tmp_xml = "/tmp/vmtui_update.xml"
        with open("/tmp/vmtui_old.xml", "w") as f: f.write(xml)
        
        py_cmd = f"""
import xml.etree.ElementTree as ET
tree = ET.parse('/tmp/vmtui_old.xml')
root = tree.getroot()
found = False
for fs in root.findall('.//filesystem'):
    driver = fs.find('driver')
    if driver is not None and driver.get('type') == 'virtiofs':
        source = fs.find('source')
        if source is not None:
            source.set('dir', '{new_path}')
            found = True
if found:
    tree.write('{tmp_xml}')
    print('OK')
"""
        res = run_cmd(["python3", "-c", py_cmd])
        if res and "OK" in res:
            run_cmd(f"virsh -c qemu:///system define {tmp_xml}", shell=True)
            msg_box(stdscr, "Libvirt XML updated with new VirtioFS path.")

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
            "3. Duplicate Active VM (Clone & Auto-Fix)",
            "4. Switch Active VM",
            "5. Console (Text Access) [Linux Only]",
            "6. Tail Install / Boot Log [Linux Only]",
            "7. Start / Restore (from Disk)",
            "8. Viewer (Graphical Access)",
            "9. USB Manager",
            "A. Hibernate (Host - ManagedSave)",
            "B. Guest Suspend (RAM/S3) [Requires GA]",
            "C. Guest Hibernate (Disk/S4) [Requires GA]",
            "D. Host Pause (Freeze in RAM)",
            "E. Resume / Wakeup",
            "F. Force Stop VM",
            "G. Delete Active VM",
            "H. Import / Rescue VM Directory",
            "I. Resize Active VM Disk",
            "J. VM Individual Settings (Per-VM Config)",
            "Q. Quit"
        ]
        
        idx = selection_menu(stdscr, "Main Menu", menu_opts)
        
        if idx == 0: setup_host(stdscr)
        elif idx == 1: create_vm_wizard(stdscr)
        elif idx == 2: duplicate_vm(stdscr)
        elif idx == 3: switch_vm_menu(stdscr)
        elif idx == 4:
            curses.endwin()
            os.system(f"virsh -c qemu:///system console {CURRENT_VM}")
        elif idx == 5: tail_vm_log(stdscr)
        elif idx == 6: start_vm(stdscr)
        elif idx == 7: launch_viewer(CURRENT_VM)
        elif idx == 8: usb_menu_logic(stdscr)
        elif idx == 9:
            msg_box(stdscr, "Host Hibernating (ManagedSave)...")
            run_cmd(["virsh", "-c", "qemu:///system", "managedsave", CURRENT_VM], check=False)
        elif idx == 10:
            msg_box(stdscr, "Sending S3 Suspend signal to Guest...")
            run_cmd(["virsh", "-c", "qemu:///system", "dompmsuspend", CURRENT_VM, "mem"], check=False)
        elif idx == 11:
            msg_box(stdscr, "Sending S4 Hibernate signal to Guest...")
            run_cmd(["virsh", "-c", "qemu:///system", "dompmsuspend", CURRENT_VM, "disk"], check=False)
        elif idx == 12:
            msg_box(stdscr, "Host Pausing VM...")
            run_cmd(["virsh", "-c", "qemu:///system", "suspend", CURRENT_VM], check=False)
        elif idx == 13:
            # Intelligent Resume/Wakeup logic
            try:
                state_raw = run_cmd(f"virsh -c qemu:///system domstate {CURRENT_VM}", shell=True, check=False)
                state = str(state_raw).lower().strip()
                
                if "pmsuspended" in state:
                    msg_box(stdscr, "Waking up Guest (S3/S4 Wakeup)...")
                    run_cmd(["virsh", "-c", "qemu:///system", "dompmwakeup", CURRENT_VM], check=False)
                elif "paused" in state:
                    msg_box(stdscr, "Resuming Host-Paused VM...")
                    run_cmd(["virsh", "-c", "qemu:///system", "resume", CURRENT_VM], check=False)
                elif "shut off" in state:
                    msg_box(stdscr, "Starting VM (Booting/S4 Restore)...")
                    run_cmd(["virsh", "-c", "qemu:///system", "start", CURRENT_VM], check=False)
                else:
                    msg_box(stdscr, f"VM is currently: {state_raw}\nAttempting normal resume...")
                    run_cmd(["virsh", "-c", "qemu:///system", "resume", CURRENT_VM], check=False)
            except Exception as e:
                msg_box(stdscr, f"Error during resume:\n{str(e)}")
        elif idx == 14: run_cmd(["virsh", "-c", "qemu:///system", "destroy", CURRENT_VM], check=False)
        elif idx == 15: delete_vm(stdscr)
        elif idx == 16: import_vm_logic(stdscr)
        elif idx == 17: resize_vm_disk(stdscr)
        elif idx == 18: edit_vm_settings(stdscr)
        elif idx == 19 or idx == -1: break

if __name__ == "__main__":
    if os.geteuid() != 0:
        args = ["sudo", "-E", sys.executable] + sys.argv
        os.execvp("sudo", args)
    try:
        curses.wrapper(main)
    except Exception as e:
        print(f"Critical Error: {e}")
