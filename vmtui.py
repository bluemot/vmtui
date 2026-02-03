#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
vmtui.py - Unified KVM Manager (Linux & Windows Support)

Combines features from 'winvmtui.py' and 'vmtui.py':
1.  **Multi-OS Support**: Create and manage both Windows (10/11) and Linux VMs.
2.  **VM Registry**: Tracks VMs across different storage paths using 'vms.json'.
3.  **Advanced Features**: TPM, Secure Boot (OVMF), VirtIO drivers for Windows.
4.  **System Health**: Automatic checks for Libvirt, Network, and Permissions.
5.  **Rescue/Import**: Import existing VM directories.

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

# Global State
VM_BASE_DIR = DEFAULT_LINUX_DIR # Default fallback
VM_REGISTRY = {} # { "vm_name": "/path/to/vm_dir" }
CURRENT_VM = ""

# Windows Specifics
VIRTIO_URL = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"
# We'll store the ISO in a common location or the windows dir
COMMON_ISO_DIR = os.path.join(DEFAULT_WINDOWS_DIR, "iso")

# --- Config & Registry Management ---

def load_config():
    global VM_REGISTRY
    
    # Load Registry
    if os.path.exists(VM_REGISTRY_FILE):
        try:
            with open(VM_REGISTRY_FILE, 'r') as f:
                VM_REGISTRY = json.load(f)
        except Exception:
            VM_REGISTRY = {}
    
    # Discovery: Check default paths if registry is empty
    if not VM_REGISTRY:
        scan_and_register(DEFAULT_LINUX_DIR)
        scan_and_register(DEFAULT_WINDOWS_DIR)

def scan_and_register(base_dir):
    if os.path.exists(base_dir):
        for d in os.listdir(base_dir):
            p = os.path.join(base_dir, d)
            if os.path.isdir(p) and d not in VM_REGISTRY:
                # Heuristic: Check for disk file
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
                rest_err = process.stderr.read()
                if rest_err: error_buffer.append(rest_err)
                break
        
        if retcode == 0: return True, None
        else: return False, "".join(error_buffer)

    except Exception as e:
        return False, str(e)

def check_system_health(stdscr):
    # Libvirt
    res = subprocess.run(["systemctl", "is-active", "libvirtd"], stdout=subprocess.PIPE, text=True)
    if res.stdout.strip() != "active":
        run_cmd_live(stdscr, ["systemctl", "start", "libvirtd"], title="Starting Libvirt...")
        time.sleep(2)

    # Network
    net_state = run_cmd("virsh -c qemu:///system net-info default | grep Active", shell=True, check=False)
    if not net_state or "yes" not in net_state:
        run_cmd("virsh -c qemu:///system net-start default", shell=True, check=False)
        run_cmd("virsh -c qemu:///system net-autostart default", shell=True, check=False)

    # SWTPM (for Windows 11)
    if shutil.which("swtpm") is None:
        return "Missing 'swtpm'. Run 'Setup Host' from menu."
    
    return None

def fix_permissions(stdscr, paths):
    """Ensures qemu/libvirt can access the specified paths using ACLs."""
    if shutil.which("setfacl") is None:
        run_cmd_live(stdscr, ["apt", "install", "-y", "acl"], title="Installing ACL tools...")

    qemu_user = "libvirt-qemu"
    # Allow traversal of user home
    run_cmd(["setfacl", "-m", f"u:{qemu_user}:x", USER_HOME], check=False)
    
    for path in paths:
        if os.path.exists(path):
            if os.path.isdir(path):
                 run_cmd(["setfacl", "-R", "-m", f"u:{qemu_user}:rx", path], check=False)
            else:
                 run_cmd(["setfacl", "-m", f"u:{qemu_user}:r", path], check=False)
                 # Ensure parent dir is executable
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
    except Exception:
        return False

# --- UI Helpers ---

def draw_header(stdscr):
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
    stdscr.move(0, 0)
    stdscr.clrtoeol()
    header = f" VMTUI (Unified) | Active VM: {CURRENT_VM} "
    stdscr.addstr(0, 0, header)
    
    state = "Stopped"
    if CURRENT_VM:
        res = run_cmd(f"virsh -c qemu:///system domstate {CURRENT_VM}", shell=True, check=False)
        if res:
            state = res.strip()
        else:
            state = "Unknown"
    
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
        except:
            return None

def usb_menu_logic(stdscr):
    """USB Manager with Auto-Refresh logic."""
    if not CURRENT_VM:
        msg_box(stdscr, "No Active VM selected.")
        return

    curses.curs_set(0)
    current_row = 0
    stdscr.timeout(2000) # Refresh device list every 2s
    
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
        stdscr.addstr(2, 2, "USB Device Manager (Auto-Refresh)", curses.A_BOLD | curses.A_UNDERLINE)
        
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
            stdscr.timeout(-1) # Reset to blocking
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
        elif key == -1: # Timeout
            continue

# --- Logic: Host Setup ---

def setup_host(stdscr):
    pkgs = [
        "qemu-kvm", "libvirt-daemon-system", "libvirt-clients", "virtinst", 
        "virt-viewer", "swtpm", "swtpm-tools", "acl", "ovmf"
    ]
    if selection_menu(stdscr, "Install/Update KVM packages?", ["No", "Yes"]) == 1:
        run_cmd_live(stdscr, ["apt", "update"], title="Updating apt...")
        run_cmd_live(stdscr, ["apt", "install", "-y"] + pkgs, title="Installing KVM Tools...")
    
    check_system_health(stdscr)
    
    if SUDO_USER:
        run_cmd(f"usermod -aG libvirt,kvm {SUDO_USER}", shell=True, check=False)
    
    msg_box(stdscr, "Host Setup Complete.\nIf you installed OVMF for the first time, a Reboot is recommended.")

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
    """Common network selection for both OS types."""
    mode = "nat"
    args = ["--network", "network=default,model=virtio"]
    
    choice = selection_menu(stdscr, "Network Configuration", [
        "NAT (Default) - Host isolated, simple",
        "Bridge - LAN accessible (requires active Ethernet)",
        "Dual (NAT + Bridge) - Recommended for Servers"
    ])
    
    if choice == 1: # Bridge
        ifaces = get_host_interfaces()
        if ifaces:
            idx = selection_menu(stdscr, "Select Interface to Bridge", ifaces)
            if idx != -1:
                args = ["--network", f"type=direct,source={ifaces[idx]},source_mode=bridge,model=virtio"]
    elif choice == 2: # Dual
        ifaces = get_host_interfaces()
        if ifaces:
            idx = selection_menu(stdscr, "Select Interface for NIC #2", ifaces)
            if idx != -1:
                args = [
                    "--network", "network=default,model=virtio",
                    "--network", f"type=direct,source={ifaces[idx]},source_mode=bridge,model=virtio"
                ]
    
    return args

def create_vm_wizard(stdscr):
    global CURRENT_VM, VM_REGISTRY
    
    err = check_system_health(stdscr)
    if err:
        msg_box(stdscr, f"System Error: {err}")
        return

    # 1. Name & Type
    name = input_box(stdscr, "VM Name: ", "my-vm")
    if not name: return
    if name in VM_REGISTRY:
        msg_box(stdscr, f"VM '{name}' already exists in registry.")
        return

    os_type = selection_menu(stdscr, "Select Operating System", [
        "Windows 10 / 11 (Requires Driver ISO)",
        "Linux (Ubuntu, Debian, Fedora, etc.)"
    ])
    
    # 2. Path
    default_base = DEFAULT_WINDOWS_DIR if os_type == 0 else DEFAULT_LINUX_DIR
    path_prompt = f"Storage Path [ Default: {default_base}/{name} ]"
    custom_path = input_box(stdscr, "Customize Path? (Empty for default)", "")
    
    vm_dir = os.path.join(default_base, name)
    if custom_path:
        vm_dir = os.path.abspath(custom_path)
        if not vm_dir.endswith(name): vm_dir = os.path.join(vm_dir, name) # Ensure subdir

    # 3. ISO Selection
    iso_start = os.path.join(USER_HOME, "Downloads")
    iso = file_browser(stdscr, iso_start)
    if not iso: return

    # 4. Create Dir & Disk
    os.makedirs(vm_dir, exist_ok=True)
    if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {vm_dir}", shell=True)
    
    disk_size = input_box(stdscr, "Disk Size (e.g. 64G, 128G): ", "64G")
    disk_path = os.path.join(vm_dir, f"{name}.qcow2")
    
    run_cmd_live(stdscr, ["qemu-img", "create", "-f", "qcow2", disk_path, disk_size], title="Creating Disk...")
    if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {disk_path}", shell=True)
    
    # 5. Network
    net_args = select_network_config(stdscr)
    
    # 6. Branch Logic
    if os_type == 0:
        create_windows_vm(stdscr, name, vm_dir, disk_path, iso, net_args)
    else:
        create_linux_vm(stdscr, name, vm_dir, disk_path, iso, net_args)

    # 7. Register
    VM_REGISTRY[name] = vm_dir
    save_registry()
    CURRENT_VM = name

def create_windows_vm(stdscr, name, vm_dir, disk_path, iso, net_args):
    # Prepare VirtIO ISO
    virtio_iso = get_virtio_iso_path()
    if not os.path.exists(virtio_iso):
        if selection_menu(stdscr, "VirtIO Drivers missing. Download?", ["No", "Yes"]) == 1:
            download_with_progress(stdscr, VIRTIO_URL, virtio_iso)
        else:
            msg_box(stdscr, "Windows installation will likely fail without network/disk drivers.")
    
    fix_permissions(stdscr, [iso, virtio_iso, disk_path, vm_dir])
    
    ram = "8192"
    vcpus = "4"
    
    cmd = [
        "virt-install", "--connect", "qemu:///system",
        f"--name={name}", "--machine", "q35",
        f"--memory={ram}", f"--vcpus={vcpus}",
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
        "--noautoconsole", "--wait", "-1"
    ] + net_args

    msg_box(stdscr, "Instructions:\n1. Click inside the Viewer window.\n2. Quickly press a key to boot from CD/DVD.\n3. Load Drivers from virtio-win CD -> amd64 -> w10.", title="Ready")
    
    success, err = run_cmd_live(stdscr, cmd, title="Installing Windows VM...")
    if success:
        launch_viewer(name)
    else:
        msg_box(stdscr, f"Installation Failed:\n{err}")

def create_linux_vm(stdscr, name, vm_dir, disk_path, iso, net_args):
    fix_permissions(stdscr, [iso, disk_path, vm_dir])
    
    ram = input_box(stdscr, "RAM (MB): ", "4096")
    vcpus = input_box(stdscr, "CPUs: ", "2")
    
    cmd = [
        "virt-install", "--connect", "qemu:///system",
        f"--name={name}",
        f"--memory={ram}", f"--vcpus={vcpus}",
        f"--cdrom={iso}",
        f"--disk=path={disk_path},device=disk,bus=virtio,format=qcow2",
        "--os-variant=generic", # generic linux
        "--graphics", "spice,listen=127.0.0.1", "--video", "qxl",
        "--channel", "spicevmc",
        "--noautoconsole"
    ] + net_args
    
    success, err = run_cmd_live(stdscr, cmd, title="Installing Linux VM...")
    if success:
        launch_viewer(name)
    else:
        msg_box(stdscr, f"Installation Failed:\n{err}")

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
    
    # Check if running
    state = run_cmd(f"virsh -c qemu:///system domstate {CURRENT_VM}", shell=True, check=False)
    if state and "running" in state:
        launch_viewer(CURRENT_VM)
        return

    # Start
    success, err = run_cmd_live(stdscr, ["virsh", "-c", "qemu:///system", "start", CURRENT_VM], title="Starting...")
    if success:
        launch_viewer(CURRENT_VM)
    else:
        msg_box(stdscr, f"Error starting VM:\n{err}")

def delete_vm(stdscr):
    if not CURRENT_VM: return
    if selection_menu(stdscr, f"DELETE VM '{CURRENT_VM}' & ALL FILES?", ["No", "Yes, Delete"]) != 1: return
    
    # 1. Libvirt Destroy
    run_cmd(f"virsh -c qemu:///system destroy {CURRENT_VM}", shell=True, check=False)
    run_cmd(f"virsh -c qemu:///system undefine {CURRENT_VM} --nvram", shell=True, check=False)
    
    # 2. Files
    path = get_vm_dir(CURRENT_VM)
    if path and os.path.exists(path):
        try:
            shutil.rmtree(path)
        except:
            pass
    
    # 3. Registry
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
    
    msg_box(stdscr, f"Imported '{name}'.\nNote: If not registered in KVM, use a 'Rescue' function or ensure .xml exists.")

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
    
    # Initial check
    if os.geteuid() != 0:
        msg_box(stdscr, "Warning: Not running as root. Some features may fail.")

    while True:
        menu_opts = [
            "1. Create New VM (Linux / Windows)",
            "2. Switch Active VM",
            "3. Start Active VM / Open Viewer",
            "4. USB Manager",
            "5. Delete Active VM",
            "6. Import / Rescue VM Directory",
            "7. Host Setup (Install KVM/Drivers)",
            "Q. Quit"
        ]
        
        idx = selection_menu(stdscr, "Main Menu", menu_opts)
        
        if idx == 0: create_vm_wizard(stdscr)
        elif idx == 1: switch_vm_menu(stdscr)
        elif idx == 2: start_vm(stdscr)
        elif idx == 3: usb_menu_logic(stdscr)
        elif idx == 4: delete_vm(stdscr)
        elif idx == 5: import_vm_logic(stdscr)
        elif idx == 6: setup_host(stdscr)
        elif idx == 7 or idx == -1: break

if __name__ == "__main__":
    # Auto-elevation
    if os.geteuid() != 0:
        args = ["sudo", "-E", sys.executable] + sys.argv
        os.execvp("sudo", args)
    
    try:
        curses.wrapper(main)
    except Exception as e:
        print(f"Critical Error: {e}")
