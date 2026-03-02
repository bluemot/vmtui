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

import logging

# --- Logging Setup ---
ENABLE_LOGGING = True # Set to True to enable logging to vmtui.log
LOG_FILE = "vmtui.log"

if ENABLE_LOGGING:
    logging.basicConfig(
        filename=LOG_FILE,
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - [%(threadName)s] %(message)s'
    )
else:
    # If disabled, we still keep a logger that does nothing to avoid errors
    logging.basicConfig(level=logging.CRITICAL) 

logger = logging.getLogger("vmtui")

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
    "Ubuntu 24.04 (Noble) Server": {
        "url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        "file": "noble-server-cloudimg-amd64.img",
        "variant": "ubuntu24.04",
        "desktop": False
    },
    "Ubuntu 24.04 (Noble) Desktop": {
        "url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        "file": "noble-server-cloudimg-amd64.img",
        "variant": "ubuntu24.04",
        "desktop": True
    },
    "Ubuntu 22.04 (Jammy) Server": {
        "url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "file": "jammy-server-cloudimg-amd64.img",
        "variant": "ubuntu22.04",
        "desktop": False
    },
    "Ubuntu 22.04 (Jammy) Desktop": {
        "url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "file": "jammy-server-cloudimg-amd64.img",
        "variant": "ubuntu22.04",
        "desktop": True
    },
    "Debian 12 (Bookworm) Server": {
        "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2",
        "file": "debian-12-generic-amd64.qcow2",
        "variant": "debian12",
        "desktop": False
    },
    "Debian 12 (Bookworm) Desktop": {
        "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2",
        "file": "debian-12-generic-amd64.qcow2",
        "variant": "debian12",
        "desktop": True
    }
}

import threading

# Global State
VM_REGISTRY = {} # { "vm_name": "/path/to/vm_dir" }
CURRENT_VM = ""
LAST_STATE_CHECK = 0
CACHED_STATE = "Stopped"
VM_STATES = {} # { "vm_name": "running/stopped..." }
STATE_LOCK = threading.Lock()

def bg_state_poller():
    global CACHED_STATE
    logger.info("Background state poller thread started.")
    while True:
        try:
            logger.debug("Starting background VM state poll.")
            start_time = time.time()
            # 1. Update overall states for all registered VMs
            new_states = {}
            res = run_cmd("virsh -c qemu:///system list --all", shell=True, check=False)
            if res:
                for line in res.split('\n'):
                    parts = line.split()
                    if len(parts) >= 3 and parts[0] != "Id":
                        vm_n = parts[1]
                        vm_s = " ".join(parts[2:])
                        new_states[vm_n] = vm_s
            
            with STATE_LOCK:
                VM_STATES.clear()
                VM_STATES.update(new_states)
                if CURRENT_VM:
                    CACHED_STATE = VM_STATES.get(CURRENT_VM, "Not Defined")
            
            logger.debug(f"Poll completed in {time.time() - start_time:.2f}s. Found {len(new_states)} VMs.")

            # 2. Check for installation complete flags (Cloud-Init)
            for name, entry in VM_REGISTRY.items():
                if isinstance(entry, dict) and entry.get("installing"):
                    log_path = os.path.join(entry.get("dir", ""), f"{name}-console.log")
                    if os.path.exists(log_path):
                        try:
                            with open(log_path, "r", errors="ignore") as f:
                                f.seek(0, 2)
                                size = f.tell()
                                f.seek(max(0, size - 4096))
                                content = f.read()
                                if "CLOUD_INIT_FINISHED_SUCCESSFULLY" in content:
                                    logger.info(f"Cloud-init finished for {name}.")
                                    entry["installing"] = False
                                    save_registry()
                        except Exception as e:
                            logger.error(f"Error checking cloud-init log for {name}: {e}")
        except Exception as e:
            logger.exception(f"Unhandled exception in background poller: {e}")
        
        time.sleep(5)

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
    # Artificial delay to prevent race conditions (replaces logging latency)
    time.sleep(0.05)
    try:
        if shell and isinstance(cmd, list):
            cmd = " ".join(cmd)
        
        logger.debug(f"Executing: {cmd}")
        result = subprocess.run(
            cmd, shell=shell, check=check, 
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            timeout=30 # Add safety timeout to prevent permanent blocking
        )
        if result.stderr:
            logger.warning(f"Cmd stderr: {result.stderr.strip()}")
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.error(f"Command timed out after 30s: {cmd}")
        return None
    except Exception as e:
        logger.error(f"Command execution failed: {cmd}, Error: {str(e)}")
        return None

def run_cmd_live(stdscr, cmd, title="Executing..."):
    h, w = stdscr.getmaxyx()
    try:
        win_h = max(2, h - 4)
        win_w = max(10, w - 4)
        win = curses.newwin(win_h, win_w, 2, 2)
        win.scrollok(True)
        win.idlok(True)
        stdscr.clear()
        draw_header(stdscr)
        if h > 2 and w > 4:
            stdscr.addstr(2, 2, f" {title} "[:w-4], curses.A_BOLD | curses.A_REVERSE)
        stdscr.refresh()
    except curses.error:
        win = None
    
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
                if win:
                    try: win.addstr(line); win.refresh()
                    except curses.error: pass
            if retcode is not None:
                rest_out = process.stdout.read()
                if rest_out and win:
                    try: win.addstr(rest_out); win.refresh()
                    except curses.error: pass
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
                        try:
                            if box_y >= 0 and box_y < h:
                                stdscr.addstr(box_y, max(0, box_x), " Downloading... "[:w-1])
                            if box_y + 2 >= 0 and box_y + 2 < h:
                                stdscr.addstr(box_y + 2, max(0, box_x), f"[{bar}] {int(percent*100)}%"[:w-1])
                            stdscr.refresh()
                        except curses.error:
                            pass
        return True
    except Exception: return False

# --- UI Helpers ---

def draw_header(stdscr):
    h, w = stdscr.getmaxyx()
    try:
        stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
        stdscr.move(0, 0)
        stdscr.clrtoeol()
        header = f" VMTUI (Restored) | Active VM: {CURRENT_VM} "
        stdscr.addstr(0, 0, header[:w-1])
        
        state = "Stopped"
        if CURRENT_VM:
            with STATE_LOCK:
                state = CACHED_STATE
                entry = VM_REGISTRY.get(CURRENT_VM)
                if isinstance(entry, dict) and entry.get("installing") and "running" in state:
                    state = "Installing... (See Log)"
        
        status = f" Status: [{state}] "
        if len(header) + len(status) < w:
            stdscr.addstr(0, max(0, w - len(status) - 1), status[:w-1])
        stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)
    except curses.error:
        pass

def msg_box(stdscr, msg, title="Message"):
    try:
        h, w = stdscr.getmaxyx()
        if h < 6 or w < 20: return # Terminal too small to show message safely
        lines = msg.split('\n')
        max_len = max([len(l) for l in lines]) if lines else 0
        box_w = min(w - 4, max(40, max_len + 6))
        
        wrapped = []
        for l in lines:
            while len(l) > box_w - 4:
                wrapped.append(l[:box_w-4])
                l = l[box_w-4:]
            wrapped.append(l)
        
        box_h = min(h - 2, len(wrapped) + 4)
        start_y = max(0, h//2 - box_h//2)
        start_x = max(0, w//2 - box_w//2)
        
        win = curses.newwin(box_h, box_w, start_y, start_x)
        win.box()
        win.addstr(0, 2, f" {title} "[:box_w-4], curses.A_BOLD)
        for i, l in enumerate(wrapped):
            if i + 2 < box_h - 1: win.addstr(i + 2, 3, l[:box_w-6])
        win.addstr(box_h - 1, max(2, box_w - 10), "[ OK ]", curses.A_REVERSE)
        win.refresh()
        win.getch()
    except curses.error:
        pass

def input_box(stdscr, prompt, default=""):
    curses.curs_set(1)
    try:
        h, w = stdscr.getmaxyx()
        if h < 6 or w < 20:
            curses.curs_set(0)
            return default
            
        # Box dimensions
        box_w = min(max(60, len(prompt) + 20), w - 2)
        box_h = 6
        start_y = max(0, (h - box_h) // 2)
        start_x = max(0, (w - box_w) // 2)
        
        win = curses.newwin(box_h, box_w, start_y, start_x)
        win.box()
        
        # Title/Prompt
        win.addstr(1, 2, prompt[:box_w-4], curses.A_BOLD)
        
        # Default hint
        if default:
            win.addstr(3, 2, f"Default: {default}"[:box_w-4], curses.A_DIM)
            
        win.refresh()
        
        curses.echo()
        # Input field at line 2
        inp = win.getstr(2, 2, box_w - 4).decode('utf-8').strip()
    except curses.error:
        inp = ""
        
    curses.noecho()
    curses.curs_set(0)
    
    return inp if inp else default

def selection_menu(stdscr, title, items, default_row=0):
    curses.curs_set(0)
    current_row = default_row if default_row < len(items) else 0
    stdscr.timeout(1000) # Auto-refresh for status
    while True:
        try:
            stdscr.erase()
            draw_header(stdscr)
            h, w = stdscr.getmaxyx()
            if h > 4 and w > 4:
                stdscr.addstr(2, 2, title[:w-4], curses.A_UNDERLINE | curses.A_BOLD)
                
                max_display = max(1, h - 6)
                start = max(0, current_row - max_display + 1) if current_row >= max_display else 0
                
                for i, item in enumerate(items[start:start+max_display]):
                    if 4+i >= h - 1: break
                    idx = start + i
                    display_text = f" {item} "[:w-6]
                    if idx == current_row:
                        stdscr.addstr(4+i, 4, display_text, curses.A_REVERSE)
                    else:
                        stdscr.addstr(4+i, 4, display_text)
            stdscr.refresh()
        except curses.error:
            pass
        
        while True:
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                return -1
            except curses.error:
                continue
                
            if key == curses.KEY_UP and current_row > 0:
                logger.debug(f"Selection Menu: UP pressed. New row: {current_row - 1}")
                current_row -= 1
                break
            elif key == curses.KEY_DOWN and current_row < len(items) - 1:
                logger.debug(f"Selection Menu: DOWN pressed. New row: {current_row + 1}")
                current_row += 1
                break
            elif key == ord('\n'):
                logger.debug(f"Selection Menu: ENTER pressed on row {current_row}")
                return current_row
            elif key == ord('q'):
                logger.debug("Selection Menu: 'q' pressed. Returning.")
                return -1
            elif key == 27:
                stdscr.timeout(200)
                next_key = stdscr.getch()
                if next_key != -1:
                    logger.debug("Selection Menu: Escape sequence detected and consumed.")
                    stdscr.timeout(0)
                    while stdscr.getch() != -1: pass
                    stdscr.timeout(1000)
                    continue # Do not break, wait for more keys
                logger.debug("Selection Menu: ESC pressed. Returning.")
                stdscr.timeout(1000)
                return -1
            elif key == -1 or key == curses.ERR:
                break
            elif key == curses.KEY_RESIZE:
                break
            else:
                continue # Ignore other keys, no redraw

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
    
    menu_items = []
    last_scan = 0
    needs_refresh = True

    while True:
        if needs_refresh or (time.time() - last_scan > 5):
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
            last_scan = time.time()
            needs_refresh = False
        
        try:
            stdscr.erase()
            draw_header(stdscr)
            h, w = stdscr.getmaxyx()
            if h > 4 and w > 4:
                stdscr.addstr(2, 2, "USB Device Manager"[:w-4], curses.A_BOLD | curses.A_UNDERLINE)
                
                max_display = max(1, h - 7)
                start = max(0, current_row - max_display + 1) if current_row >= max_display else 0
                
                for i, item in enumerate(menu_items[start:start+max_display]):
                    if 4+i >= h - 2: break
                    display_str, _, is_attached = item
                    y = 4 + i
                    attr = curses.color_pair(2) if is_attached else curses.color_pair(1)
                    idx = start + i
                    if idx == current_row: attr |= curses.A_REVERSE
                    stdscr.addstr(y, 4, display_str[:w-6], attr)
                stdscr.addstr(h-2, 2, "ENTER to Toggle, 'q' to Back, 'r' to Refresh"[:w-4])
            stdscr.refresh()
        except curses.error:
            pass
        
        while True:
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                stdscr.timeout(-1)
                return
            except curses.error:
                continue
                
            if key == curses.KEY_UP and current_row > 0:
                logger.debug(f"USB Menu: UP pressed. New row: {current_row - 1}")
                current_row -= 1
                break # Only break to redraw, not to re-scan
            elif key == curses.KEY_DOWN and current_row < len(menu_items) - 1:
                logger.debug(f"USB Menu: DOWN pressed. New row: {current_row + 1}")
                current_row += 1
                break # Only break to redraw, not to re-scan
            elif key == ord('r'):
                logger.debug("USB Menu: 'r' (refresh) pressed.")
                needs_refresh = True
                break # Break to re-scan
            elif key == ord('q'):
                logger.debug("USB Menu: 'q' pressed. Returning.")
                stdscr.timeout(-1)
                return
            elif key == 27: 
                stdscr.timeout(200)
                next_key = stdscr.getch()
                stdscr.timeout(2000)
                if next_key != -1:
                    logger.debug("USB Menu: Escape sequence detected and consumed.")
                    stdscr.timeout(0)
                    while stdscr.getch() != -1: pass
                    stdscr.timeout(2000)
                    continue
                logger.debug("USB Menu: ESC pressed. Returning.")
                stdscr.timeout(-1)
                return
            elif key == ord('\n'):
                logger.debug(f"USB Menu: ENTER pressed on row {current_row}")
                sel_display, sel_dev, sel_attached = menu_items[current_row]
                if sel_dev is None: break
                action = "detach-device" if sel_attached else "attach-device"
                logger.info(f"USB Menu: Performing {action} for {sel_dev['vid']}:{sel_dev['pid']}")
                xml_content = f"<hostdev mode='subsystem' type='usb' managed='yes'><source><vendor id='0x{sel_dev['vid']}'/><product id='0x{sel_dev['pid']}'/></source></hostdev>"
                xml_path = "/tmp/vmtui_usb.xml"
                with open(xml_path, "w") as f: f.write(xml_content)
                run_cmd(["virsh", action, CURRENT_VM, xml_path, "--live"], check=False)
                time.sleep(0.5)
                needs_refresh = True
                break # Re-scan after action
            elif key == -1 or key == curses.ERR:
                # This is the timeout for draw_header update
                break 
            elif key == curses.KEY_RESIZE:
                break
            else:
                continue

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
                "cloud-image-utils", "virtiofsd", "unzip", "wireless-tools", "bridge-utils"
            ]
            run_cmd_live(stdscr, ["apt", "update"], title="Updating apt...")
            run_cmd_live(stdscr, ["apt", "install", "-y"] + pkgs, title="Installing KVM Tools...")
            check_system_health(stdscr)
            if SUDO_USER:
                run_cmd(f"usermod -aG libvirt,kvm {SUDO_USER}", shell=True, check=False)
            msg_box(stdscr, "Host Setup Complete.\nPlease reboot if you just installed these for the first time.")
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
        "Linux Cloud Image (Auto-Install)",
        "Linux (ISO Install - Manual)"
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

    if os_type == 0: # Windows ISO
        iso_start = os.path.join(USER_HOME, "Downloads")
        iso = file_browser(stdscr, iso_start)
        if not iso: return
        run_cmd_live(stdscr, ["qemu-img", "create", "-f", "qcow2", disk_path, disk_size], title="Creating Disk...")
        if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {disk_path}", shell=True)
        create_windows_vm(stdscr, name, vm_dir, disk_path, iso, net_args)
    elif os_type == 1: # Linux Cloud-Init
        img_names = list(LINUX_IMAGES.keys())
        idx = selection_menu(stdscr, "Select Linux Distro", img_names)
        if idx == -1: return
        img_data = LINUX_IMAGES[img_names[idx]]
        create_linux_vm_cloud(stdscr, name, vm_dir, disk_path, disk_size, img_data, net_args)
    elif os_type == 2: # Linux ISO Manual
        iso_start = os.path.join(USER_HOME, "Downloads")
        iso = file_browser(stdscr, iso_start)
        if not iso: return
        run_cmd_live(stdscr, ["qemu-img", "create", "-f", "qcow2", disk_path, disk_size], title="Creating Disk...")
        if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {disk_path}", shell=True)
        create_linux_vm_iso(stdscr, name, vm_dir, disk_path, iso, net_args)

    VM_REGISTRY[name] = {"dir": vm_dir, "host_share": HOST_SHARE_DIR, "installing": (os_type == 1)}
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
        f"--memory=12288", "--vcpus=4",
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

def create_linux_vm_iso(stdscr, name, vm_dir, disk_path, iso, net_args):
    fix_permissions(stdscr, [iso, disk_path, vm_dir])
    
    cmd = [
        "virt-install", "--connect", "qemu:///system",
        f"--name={name}", "--machine", "q35",
        f"--memory=12288", "--vcpus=4",
        f"--disk=path={iso},device=cdrom,bus=sata,boot.order=1",
        f"--disk=path={disk_path},device=disk,bus=virtio,format=qcow2,boot.order=2",
        "--os-variant=generic",
        "--graphics", "spice,listen=127.0.0.1", "--video", "qxl",
        "--channel", "spicevmc",
        "--cpu", "host-passthrough",
        "--boot", "uefi,menu=on",
        "--memorybacking", "source.type=memfd,access.mode=shared",
        f"--filesystem", f"source={HOST_SHARE_DIR},target=host_share,driver.type=virtiofs,accessmode=passthrough",
        "--noautoconsole"
    ] + net_args

    success, err = run_cmd_live(stdscr, cmd, title=f"Starting Linux ISO Install for {name}...")
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

    packages_list = [
        "build-essential", "linux-headers-generic", "bear", "net-tools",
        "nfs-common", "wpasupplicant", "hostapd", "network-manager",
        "rfkill", "iw", "wireless-tools", "unzip", "vim",
        "libnl-genl-3-dev", "libnl-3-dev", "libnl-route-3-dev",
        "libssl-dev", "pkgconf", "bridge-utils", "curl", "samba", "sshfs",
        "openssh-server", "xrdp"
    ]
    if img_data.get("desktop"):
        if "debian" in img_data.get("variant", ""):
            packages_list.append("task-gnome-desktop")
        else:
            packages_list.append("ubuntu-desktop")
            packages_list.append("kde-plasma-desktop")
            
    packages_yaml = "\n".join([f"  - {p}" for p in packages_list])
    
    desktop_target_cmd = "  - systemctl set-default graphical.target" if img_data.get("desktop") else ""

    user_data = f"""#cloud-config
hostname: {name}
manage_etc_hosts: true
ssh_pwauth: true
package_update: true
package_upgrade: false
output: {{all: '| tee -a /var/log/cloud-init-output.log > /dev/ttyS1'}}
final_message: "CLOUD_INIT_FINISHED_SUCCESSFULLY"
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
{desktop_target_cmd}

packages:
{packages_yaml}

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
        f"--name={name}", "--memory=12288", "--vcpus=4",
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
        
        msg = f"VM {name} Created.\nAuto-rebooting after setup completes.\nLogin: ubuntu / password"
        if img_data.get("desktop"):
            msg += "\n\nNOTE: Desktop GUI installation is running in the background.\nIt may take 10-20 minutes before the GUI appears!"
            
        msg_box(stdscr, msg)
    else:
        msg_box(stdscr, f"Error:\n{err}")

# --- Logic: Management ---

def tail_vm_log(stdscr):
    if not CURRENT_VM:
        msg_box(stdscr, "No Active VM selected.")
        return
    entry = VM_REGISTRY.get(CURRENT_VM)
    if isinstance(entry, dict):
        log_path = os.path.join(entry.get("dir", ""), f"{CURRENT_VM}-console.log")
        if os.path.exists(log_path):
            curses.endwin()
            print(f"--- Tailing Install/Boot log for {CURRENT_VM} ---")
            print("Press Ctrl+C to stop viewing and return to menu.")
            try:
                subprocess.run(["tail", "-f", "-n", "50", log_path])
            except KeyboardInterrupt:
                pass
            return
    msg_box(stdscr, "No console log found for this VM.\n(Only Linux Cloud-Init VMs have this log)")

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
        
    # Get active VMs
    active_vms = []
    res = run_cmd("virsh -c qemu:///system list --name --state-running", shell=True, check=False)
    if res:
        active_vms = [vm.strip() for vm in res.split('\n') if vm.strip()]

    menu_items = []
    for vm in vms:
        if vm in active_vms:
            menu_items.append(f"{vm} [Running]")
        else:
            menu_items.append(vm)
            
    menu_items.append("Cancel")
    
    # Try to select the currently active VM by default if it's in the list
    default_idx = 0
    if active_vms and CURRENT_VM not in active_vms:
        # If current is not running but there is a running one, point to first running
        for i, vm in enumerate(vms):
            if vm in active_vms:
                default_idx = i
                break
    elif CURRENT_VM in vms:
         default_idx = vms.index(CURRENT_VM)

    idx = selection_menu(stdscr, "Select Active VM", menu_items, default_row=default_idx)
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
        "3. Change RAM / CPU Allocation",
        "4. Back"
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
    elif choice == 2:
        change_vm_resources(stdscr, CURRENT_VM)

def change_vm_resources(stdscr, vm_name):
    # Get current settings if possible
    ram = input_box(stdscr, "New RAM Size (MB): ", "12288")
    cpu = input_box(stdscr, "New CPU Cores: ", "4")
    
    if not ram or not cpu: return
    
    if selection_menu(stdscr, f"Update {vm_name} to {ram}MB RAM and {cpu} CPUs?", ["Cancel", "Confirm"]) == 1:
        # We update both --config (permanent) and attempt --live (if running)
        # Note: setmaxmem and setvcpus --maximum usually require the VM to be SHUT OFF.
        
        state = run_cmd(f"virsh -c qemu:///system domstate {vm_name}", shell=True, check=False)
        is_running = state and "running" in state
        
        if is_running:
            msg_box(stdscr, "Note: VM is running. Max RAM/CPU changes require a REBOOT to take effect.\nApplying to configuration...")

        # Update Memory
        run_cmd(f"virsh -c qemu:///system setmaxmem {vm_name} {ram}M --config", shell=True, check=False)
        run_cmd(f"virsh -c qemu:///system setmem {vm_name} {ram}M --config", shell=True, check=False)
        
        # Update CPU
        run_cmd(f"virsh -c qemu:///system setvcpus {vm_name} {cpu} --config --maximum", shell=True, check=False)
        run_cmd(f"virsh -c qemu:///system setvcpus {vm_name} {cpu} --config", shell=True, check=False)
        
        msg_box(stdscr, f"Hardware resources updated for {vm_name}.\nPlease SHUT DOWN and START the VM for all changes to apply.")

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

def disable_mouse_tracking():
    # Send escape sequences to disable various terminal mouse tracking modes
    # \033[?1000l: Disable X11 mouse tracking
    # \033[?1002l: Disable cell motion mouse tracking
    # \033[?1003l: Disable all motion mouse tracking
    # \033[?1006l: Disable SGR mouse tracking
    sys.stdout.write('\033[?1000l\033[?1002l\033[?1003l\033[?1006l')
    sys.stdout.flush()

def main(stdscr):
    disable_mouse_tracking()
    # Start Background Poller
    poller = threading.Thread(target=bg_state_poller, daemon=True)
    poller.start()
    
    global CURRENT_VM
    load_config()
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_GREEN, -1)
    curses.init_pair(3, curses.COLOR_RED, -1)
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)
    
    if os.geteuid() != 0:
        msg_box(stdscr, "Warning: Not running as root. Some features may fail.")

    if not CURRENT_VM:
        res = run_cmd("virsh -c qemu:///system list --name --state-running", shell=True, check=False)
        if res:
            active_vms = [vm.strip() for vm in res.split('\n') if vm.strip()]
            if active_vms:
                CURRENT_VM = active_vms[0]
                
    while True:
        menu_opts = [
            "1. Setup Host Environment",
            "2. Create New VM (Linux / Windows)",
            "3. Switch Active VM",
            "4. Console (Text Access) [Linux Only]",
            "5. Tail Install / Boot Log [Linux Only]",
            "6. Start / Restore (from Disk)",
            "7. Viewer (Graphical Access)",
            "8. USB Manager",
            "9. Hibernate (Save to Disk)",
            "A. Pause (Freeze in RAM)",
            "B. Resume (Unfreeze RAM)",
            "C. Force Stop VM",
            "D. Delete Active VM",
            "E. Import / Rescue VM Directory",
            "F. Resize Active VM Disk",
            "G. VM Individual Settings (Per-VM Config)",
            "Q. Quit"
        ]
        
        idx = selection_menu(stdscr, "Main Menu", menu_opts)
        
        if idx == 0: setup_host(stdscr)
        elif idx == 1: create_vm_wizard(stdscr)
        elif idx == 2: switch_vm_menu(stdscr)
        elif idx == 3:
            curses.endwin()
            os.system(f"virsh -c qemu:///system console {CURRENT_VM}")
        elif idx == 4: tail_vm_log(stdscr)
        elif idx == 5: start_vm(stdscr)
        elif idx == 6: launch_viewer(CURRENT_VM)
        elif idx == 7: usb_menu_logic(stdscr)
        elif idx == 8:
             msg_box(stdscr, "Hibernating...")
             run_cmd(["virsh", "-c", "qemu:///system", "managedsave", CURRENT_VM], check=False)
        elif idx == 9: run_cmd(["virsh", "-c", "qemu:///system", "suspend", CURRENT_VM], check=False)
        elif idx == 10: run_cmd(["virsh", "-c", "qemu:///system", "resume", CURRENT_VM], check=False)
        elif idx == 11: run_cmd(["virsh", "-c", "qemu:///system", "destroy", CURRENT_VM], check=False)
        elif idx == 12: delete_vm(stdscr)
        elif idx == 13: import_vm_logic(stdscr)
        elif idx == 14: resize_vm_disk(stdscr)
        elif idx == 15: edit_vm_settings(stdscr)
        elif idx == 16 or idx == -1: break

if __name__ == "__main__":
    if os.geteuid() != 0:
        args = ["sudo", "-E", sys.executable] + sys.argv
        os.execvp("sudo", args)
    
    # Try to disable mouse tracking at the terminal level early
    try:
        sys.stdout.write('\033[?1000l\033[?1002l\033[?1003l\033[?1006l')
        sys.stdout.flush()
    except: pass

    try:
        curses.wrapper(main)
    except Exception as e:
        logger.exception(f"Critical Application Crash: {e}")
        print(f"Critical Error (Check vmtui.log): {e}")
    except KeyboardInterrupt:
        logger.info("Application exited by user via KeyboardInterrupt.")
