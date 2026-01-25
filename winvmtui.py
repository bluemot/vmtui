#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
winvmtui.py - Windows KVM Manager (v11: Delete Feature)

Updates:
1. FEATURE: Added 'Delete VM' option to cleanly remove VM and files.
2. RETAINS: All previous Win11/Q35/ACL fixes.

Usage: sudo python3 winvmtui.py
"""

import curses
import os
import sys
import subprocess
import time
import shutil

# --- Configuration ---
SUDO_USER = os.environ.get('SUDO_USER')
if SUDO_USER:
    USER_HOME = os.path.expanduser(f"~{SUDO_USER}")
else:
    USER_HOME = os.path.expanduser("~")

VM_BASE_DIR = os.path.abspath("win_vms")
VIRTIO_URL = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/stable-virtio/virtio-win.iso"
VIRTIO_ISO_PATH = os.path.join(VM_BASE_DIR, "virtio-win.iso")

RAM_SIZE = 8192
VCPUS = 4
DEFAULT_DISK_SIZE = "128G"
CURRENT_VM = "windows-dev-vm"

# --- Helpers ---

def get_vm_dir(vm_name):
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

def run_cmd_live_debug(stdscr, cmd, title="Executing..."):
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
                try:
                    win.addstr(line)
                    win.refresh()
                except curses.error: pass
            
            if retcode is not None:
                rest_out = process.stdout.read()
                if rest_out: win.addstr(rest_out)
                rest_err = process.stderr.read()
                if rest_err: error_buffer.append(rest_err)
                break
        
        if retcode == 0:
            return True, None
        else:
            return False, "".join(error_buffer)

    except Exception as e:
        return False, str(e)

def check_system_health(stdscr):
    res = subprocess.run(["systemctl", "is-active", "libvirtd"], stdout=subprocess.PIPE, text=True)
    if res.stdout.strip() != "active":
        run_cmd_live_debug(stdscr, ["systemctl", "start", "libvirtd"], title="Starting Libvirt...")
        time.sleep(2)

    net_state = run_cmd("virsh -c qemu:///system net-info default | grep Active", shell=True, check=False)
    if not net_state or "yes" not in net_state:
        run_cmd("virsh -c qemu:///system net-start default", shell=True, check=False)
        run_cmd("virsh -c qemu:///system net-autostart default", shell=True, check=False)

    if shutil.which("swtpm") is None:
        return "Missing 'swtpm'. Run 'Setup Host' again."
    
    return None

def fix_permissions(stdscr, paths):
    if shutil.which("setfacl") is None:
        run_cmd_live_debug(stdscr, ["apt", "install", "-y", "acl"], title="Installing ACL tools...")

    qemu_user = "libvirt-qemu"
    run_cmd(["setfacl", "-m", f"u:{qemu_user}:x", USER_HOME], check=False)
    
    for path in paths:
        if os.path.exists(path):
            if os.path.isdir(path):
                 run_cmd(["setfacl", "-R", "-m", f"u:{qemu_user}:rx", path], check=False)
            else:
                 run_cmd(["setfacl", "-m", f"u:{qemu_user}:r", path], check=False)
                 parent = os.path.dirname(path)
                 run_cmd(["setfacl", "-m", f"u:{qemu_user}:x", parent], check=False)

def launch_viewer_as_user(vm_name):
    cmd = ["virt-viewer", "--connect", "qemu:///system", "--attach", vm_name]
    if SUDO_USER:
        cmd = ["sudo", "-E", "-u", SUDO_USER] + cmd
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def check_root():
    if os.geteuid() != 0:
        args = ["sudo", "-E", sys.executable] + sys.argv
        os.execvp("sudo", args)

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

def draw_header(stdscr):
    h, w = stdscr.getmaxyx()
    stdscr.attron(curses.color_pair(4) | curses.A_BOLD)
    stdscr.move(0, 0)
    stdscr.clrtoeol()
    header = f" WinVMTUI v11 | VM: {CURRENT_VM} "
    stdscr.addstr(0, 0, header)
    
    state = "Stopped"
    res = run_cmd(f"virsh -c qemu:///system domstate {CURRENT_VM}", shell=True, check=False)
    if res: state = res.strip()
    else: state = "NOT FOUND"
    
    status = f" Status: [{state}] "
    if len(header) + len(status) < w:
        stdscr.addstr(0, w - len(status) - 1, status)
    stdscr.attroff(curses.color_pair(4) | curses.A_BOLD)

def msg_box(stdscr, msg, title="Message"):
    h, w = stdscr.getmaxyx()
    lines = msg.split('\n')
    max_len = max([len(l) for l in lines]) if lines else 0
    box_w = min(w - 4, max_len + 6)
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
            if start + i == current_row:
                stdscr.addstr(4+i, 4, f" {item} ", curses.A_REVERSE)
            else:
                stdscr.addstr(4+i, 4, f" {item} ")
        key = stdscr.getch()
        if key == curses.KEY_UP and current_row > 0: current_row -= 1
        elif key == curses.KEY_DOWN and current_row < len(items) - 1: current_row += 1
        elif key == ord('\n'): return current_row
        elif key == ord('q') or key == 27: return -1

def input_box(stdscr, prompt, default=""):
    curses.echo()
    h, w = stdscr.getmaxyx()
    stdscr.addstr(h-3, 2, prompt)
    stdscr.addstr(h-3, len(prompt)+3, default)
    inp = stdscr.getstr(h-3, len(prompt)+3, 40)
    curses.noecho()
    return inp.decode('utf-8').strip() or default

def file_browser(stdscr, start_path):
    current_path = os.path.abspath(start_path)
    if not os.path.exists(current_path): current_path = "/"
    while True:
        try:
            entries = sorted(os.listdir(current_path))
            dirs = [d for d in entries if os.path.isdir(os.path.join(current_path, d))]
            files = [f for f in entries if f.lower().endswith('.iso')]
            items = [".. (Go Up)"] + [f"/{d}" for d in dirs] + files
            idx = selection_menu(stdscr, f"ISO Select: {current_path}", items)
            if idx == -1: return None
            sel = items[idx]
            if sel == ".. (Go Up)": current_path = os.path.dirname(current_path)
            elif sel.startswith("/"): current_path = os.path.join(current_path, sel[1:])
            else: return os.path.join(current_path, sel)
        except: return None

# --- Features ---

def switch_vm_menu(stdscr):
    global CURRENT_VM
    if not os.path.exists(VM_BASE_DIR):
        os.makedirs(VM_BASE_DIR, exist_ok=True)
    vms_dirs = [d for d in os.listdir(VM_BASE_DIR) if os.path.isdir(os.path.join(VM_BASE_DIR, d))]
    vms_dirs.sort()
    if not vms_dirs:
        msg_box(stdscr, "No VMs found in 'win_vms/' directory.")
        return
    items = vms_dirs + ["[ Cancel ]"]
    idx = selection_menu(stdscr, "Select Active VM", items)
    if idx != -1 and idx < len(vms_dirs):
        CURRENT_VM = vms_dirs[idx]
        msg_box(stdscr, f"Switched to: {CURRENT_VM}")

def delete_vm_logic(stdscr):
    # Confirm
    sel = selection_menu(stdscr, f"DELETE VM '{CURRENT_VM}'?", ["NO, Cancel", "YES, DELETE EVERYTHING"])
    if sel != 1: return

    vm_dir = get_vm_dir(CURRENT_VM)
    
    # 1. Destroy & Undefine (Libvirt)
    run_cmd_live_debug(stdscr, ["echo", f"Stopping & Undefining {CURRENT_VM}..."], title="Deleting...")
    run_cmd(f"virsh -c qemu:///system destroy {CURRENT_VM}", shell=True, check=False)
    time.sleep(1)
    run_cmd(f"virsh -c qemu:///system undefine {CURRENT_VM} --nvram", shell=True, check=False)
    
    # 2. Delete Files
    if os.path.exists(vm_dir):
        run_cmd_live_debug(stdscr, ["echo", f"Removing directory: {vm_dir}"], title="Deleting...")
        try:
            shutil.rmtree(vm_dir)
            msg_box(stdscr, f"VM '{CURRENT_VM}' and all files have been deleted.", title="Deleted")
        except Exception as e:
            msg_box(stdscr, f"Failed to delete directory: {e}", title="Error")
    else:
        msg_box(stdscr, f"VM '{CURRENT_VM}' unregistered, but directory not found.", title="Done")

def force_cleanup_vm(stdscr, vm_name):
    run_cmd_live_debug(stdscr, ["echo", f"Cleaning up zombie VM: {vm_name}..."], title="Cleanup")
    run_cmd(f"virsh -c qemu:///system destroy {vm_name}", shell=True, check=False)
    time.sleep(1)
    run_cmd(f"virsh -c qemu:///system undefine {vm_name} --nvram", shell=True, check=False)
    time.sleep(0.5)

def start_existing_vm(stdscr):
    state = run_cmd(f"virsh -c qemu:///system domstate {CURRENT_VM}", shell=True, check=False)
    if state and "running" in state:
        msg_box(stdscr, f"VM '{CURRENT_VM}' is already running.\nOpening viewer...", title="Info")
        launch_viewer_as_user(CURRENT_VM)
        return
    vm_exists = run_cmd(f"virsh -c qemu:///system dominfo {CURRENT_VM}", shell=True, check=False)
    if not vm_exists:
        msg_box(stdscr, f"VM '{CURRENT_VM}' does not exist in KVM.\nPlease create it first.", title="Error")
        return
    success, err = run_cmd_live_debug(stdscr, ["virsh", "-c", "qemu:///system", "start", CURRENT_VM], title="Starting VM...")
    if success:
        time.sleep(1)
        launch_viewer_as_user(CURRENT_VM)
        msg_box(stdscr, "VM Started successfully.\nViewer launched.", title="Success")
    else:
        msg_box(stdscr, f"Failed to start VM:\n{err}", title="Error")

def setup_host(stdscr):
    pkgs = ["qemu-kvm", "libvirt-daemon-system", "libvirt-clients", "virtinst", "virt-viewer", "swtpm", "swtpm-tools", "acl", "ovmf"]
    run_cmd_live_debug(stdscr, ["apt", "update"], title="Updating...")
    run_cmd_live_debug(stdscr, ["apt", "install", "-y"] + pkgs, title="Installing...")
    check_system_health(stdscr)
    if SUDO_USER:
        run_cmd(f"usermod -aG libvirt,kvm {SUDO_USER}", shell=True, check=False)
    msg_box(stdscr, "Host Setup Complete.\n(Please REBOOT if you just installed 'ovmf')")

def create_vm(stdscr):
    global CURRENT_VM
    err = check_system_health(stdscr)
    if err:
        msg_box(stdscr, f"System Error: {err}", title="Pre-check Failed")
        return
    new_name = input_box(stdscr, f"Name [{CURRENT_VM}]: ", CURRENT_VM)
    if new_name: CURRENT_VM = new_name
    disk_size = input_box(stdscr, f"Disk Size [{DEFAULT_DISK_SIZE}]: ", DEFAULT_DISK_SIZE)
    if not disk_size: disk_size = DEFAULT_DISK_SIZE
    vm_dir = get_vm_dir(CURRENT_VM)
    vm_exists = run_cmd(f"virsh -c qemu:///system dominfo {CURRENT_VM}", shell=True, check=False)
    if vm_exists or os.path.exists(vm_dir):
        sel = selection_menu(stdscr, f"VM '{CURRENT_VM}' exists!", ["Cancel", "Overwrite"])
        if sel != 1: return
        force_cleanup_vm(stdscr, CURRENT_VM)
        shutil.rmtree(vm_dir, ignore_errors=True)
    iso = file_browser(stdscr, os.path.join(USER_HOME, "Downloads"))
    if not iso: return
    os.makedirs(vm_dir, exist_ok=True)
    if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {vm_dir}", shell=True)
    if not os.path.exists(VIRTIO_ISO_PATH):
        download_with_progress(stdscr, VIRTIO_URL, VIRTIO_ISO_PATH)
    disk_path = os.path.join(vm_dir, f"{CURRENT_VM}.qcow2")
    run_cmd_live_debug(stdscr, ["qemu-img", "create", "-f", "qcow2", disk_path, disk_size], title=f"Creating {disk_size} Disk...")
    if SUDO_USER: run_cmd(f"chown {SUDO_USER}:{SUDO_USER} {disk_path}", shell=True)
    fix_permissions(stdscr, [iso, VIRTIO_ISO_PATH, disk_path, vm_dir])
    msg_box(stdscr, "IMPORTANT INSTRUCTIONS:\n1. Load Driver -> virtio-win -> amd64 -> w10\n2. Select 'Red Hat VirtIO SCSI controller'\n\nTIMING IS CRITICAL:\nThe VM will start in 'Paused' mode.\nOnce the window opens, click inside it, then press ENTER here to Resume.", title="READ CAREFULLY")
    install_cmd = [
        "virt-install",
        "--connect", "qemu:///system",
        f"--name={CURRENT_VM}",
        "--machine", "q35",
        f"--memory={RAM_SIZE}",
        f"--vcpus={VCPUS}",
        f"--cdrom={iso}",
        f"--disk=path={disk_path},device=disk,bus=virtio,format=qcow2",
        f"--disk=path={VIRTIO_ISO_PATH},device=cdrom",
        "--os-variant=win10",
        "--graphics", "spice,listen=127.0.0.1",
        "--video", "qxl",
        "--channel", "spicevmc",
        "--cpu", "host-passthrough",
        "--boot", "uefi,menu=on",
        "--features", "smm=on",
        "--tpm", "backend.type=emulator,backend.version=2.0,model=tpm-tis",
        "--noautoconsole",
        "--wait", "-1"
    ]
    try:
        run_cmd_live_debug(stdscr, ["echo", "Initializing VM..."], title="Setup")
        subprocess.Popen(install_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)
        run_cmd(f"virsh -c qemu:///system suspend {CURRENT_VM}", shell=True, check=False)
        launch_viewer_as_user(CURRENT_VM)
        msg_box(stdscr, "The VM is currently PAUSED.\n\n1. Ensure the 'virt-viewer' window is open.\n2. Click inside the viewer window.\n3. Get ready to press any key (Space/Enter).\n\nPress ENTER on this keyboard to RESUME VM.", title="Ready to Install?")
        run_cmd(f"virsh -c qemu:///system resume {CURRENT_VM}", shell=True, check=False)
    except Exception as e:
        msg_box(stdscr, f"Error: {e}", title="Exception")

def main(stdscr):
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(4, curses.COLOR_WHITE, curses.COLOR_BLUE)
    check_system_health(stdscr)
    while True:
        opts = [
            "1. Setup Host (Install OVMF/TPM)", 
            "2. Create New Windows VM", 
            "3. Start Existing VM",
            "4. Open Desktop Viewer", 
            "5. Switch Active VM",
            "6. Force Stop VM",
            "7. Delete VM (Destroy & Delete Files)", # NEW
            "Q. Quit"
        ]
        idx = selection_menu(stdscr, "Main Menu", opts)
        if idx == 0: setup_host(stdscr)
        elif idx == 1: create_vm(stdscr)
        elif idx == 2: start_existing_vm(stdscr)
        elif idx == 3: 
            curses.endwin()
            launch_viewer_as_user(CURRENT_VM)
        elif idx == 4: switch_vm_menu(stdscr)
        elif idx == 5: force_cleanup_vm(stdscr, CURRENT_VM)
        elif idx == 6: delete_vm_logic(stdscr) # NEW
        elif idx == 7 or idx == -1: break

if __name__ == "__main__":
    check_root()
    curses.wrapper(main)