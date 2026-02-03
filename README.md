# VMTUI - Unified KVM/QEMU Management Tool (Linux & Windows)

**VMTUI** is a unified Python TUI (Text User Interface) tool designed for Linux developers to easily create and manage KVM virtual machines.

It combines the best features of Linux Cloud-Init automation and Windows ISO installation into a single, robust utility.

## 🌟 Key Features

### 🐧 Linux Features (Cloud-Init Automation)
*   **Auto-Install**: Automatically downloads and installs Ubuntu (22.04/24.04) or Debian 12 Cloud Images.
*   **Zero-Config Setup**: Automatically configures the `ubuntu` user (password: `password`), SSH access, and hostname.
*   **Shared Folder**: Host's `~/driver_projects` is automatically mounted to `/home/ubuntu/host_share` in the guest via high-performance **VirtioFS**.
*   **Pre-installed Packages**: Includes essential tools for driver development: `build-essential`, `linux-headers`, `wireless-tools`, `unzip`, `bear`, `samba`, `sshfs`, etc.
*   **Dual Console**: Supports both interactive `virsh console` and background kernel logging to file (`ttyS1`).

### 🪟 Windows Features (ISO Support)
*   **Windows 10/11 Support**: Optimized wizard for installing Windows via ISO.
*   **Driver Handling**: Automatically handles `virtio-win.iso` download and attachment for disk/network drivers.
*   **TPM 2.0 & Secure Boot**: Enabled by default (using `swtpm` and `ovmf`) to support Windows 11 requirements.

### ⚙️ General Management
*   **VM Registry**: Tracks VMs across different storage paths using `vms.json`.
*   **Zombie Cleanup**: Smart detection to clean up conflicting VM states (defined but missing files, or files without definition).
*   **USB Hotplug**: Graphical menu to Attach/Detach host USB devices on the fly.
*   **Power Management**: Start, Stop, Hibernate (Save to Disk), and Suspend (RAM).
*   **Import/Rescue**: Import existing VM directories into the manager.

---

## 🚀 Installation & Usage

### 1. Prerequisites
*   Host OS: Ubuntu 22.04 / 24.04 LTS (Recommended)
*   Python 3

### 2. Setup Host Environment
First time running? Use the built-in setup option:
1.  Run `./vmtui.py`
2.  Select **"1. Setup Host Environment"**
3.  This will install KVM, Libvirt, VirtIO drivers, and other necessary packages.
4.  **REBOOT** your host machine.

### 3. Running VMTUI
```bash
chmod +x vmtui.py
sudo ./vmtui.py
```

---

## 📖 Main Menu Guide

### 1. Setup Host Environment
Installs all required dependencies (`qemu-kvm`, `libvirt`, `virtinst`, `swtpm`, `unzip`, etc.) and configures user permissions.

### 2. Create New VM
*   **Linux Cloud Image**: Select Ubuntu/Debian, set disk size, and let VMTUI do the rest. The VM will auto-reboot once to finalize setup.
*   **Windows ISO**: Point to your Windows ISO. VMTUI will attach the VirtIO driver ISO automatically.

### 3. Switch Active VM
Select which VM you want to manage from the registry.

### 4. Console (Text Access) [Linux Only]
Connects to the serial console (`ttyS0`). Useful for kernel debugging or headless operation.
*   **Exit**: Press `Ctrl + ]`
*   **Login**: `ubuntu` / `password`

### 5. Start / Restore
Boots the VM or restores it from a hibernated state (managedsave).

### 6. Viewer (Graphical Access)
Launches `virt-viewer` (SPICE/VNC) for a graphical desktop experience. Essential for Windows usage.

### 7. USB Manager
Pass-through Host USB devices to the VM.
*   **Attach**: Connect a device (e.g., Wifi Dongle) to the VM.
*   **Detach**: Return the device to the Host.
*   **Warning**: Always detach USB devices before rebooting the VM to avoid host kernel deadlocks.

### 8-A. Power Options
*   **Hibernate**: Saves VM state to disk and powers off.
*   **Pause**: Freezes VM in RAM.
*   **Resume**: Unfreezes VM.

### B. Force Stop VM
Equivalent to pulling the power plug. Use if the VM is unresponsive.

### D. Import / Rescue VM Directory
If you have an existing VM folder (with a `.qcow2` file), use this to register it with VMTUI.

---

## 🔧 Windows Installation Tips

When installing **Windows**, the installer will not see the virtual hard drive by default. You must load the VirtIO drivers:

1.  When asked "Where do you want to install Windows?", click **Load driver**.
2.  Click **Browse**.
3.  Navigate to the `virtio-win` CD drive.
4.  Go to `amd64` -> `w10` (Use w10 for Win10 and Win11).
5.  Select **"Red Hat VirtIO SCSI controller"**.
6.  The drive should now appear.

**After Installation (in Windows):**
1.  Open the `virtio-win` CD drive in File Explorer.
2.  Run `virtio-win-guest-tools.exe` to install network, video, and balloon drivers.
3.  Reboot the VM.

---

## 🐞 Troubleshooting

*   **Console is black?** Press `Enter` to wake up the login prompt.
*   **VM "Already Exists"?** VMTUI detects if a VM name is taken in Libvirt or the file system. It offers an "Overwrite" option to cleanly wipe the old one.
*   **Permission Denied?** VMTUI tries to fix permissions using `setfacl`. Ensure you ran `Setup Host` and rebooted.
*   **SSH by Hostname?** To SSH using `ssh ubuntu@my-vm-name`, install `libnss-libvirt` on the Host:
    ```bash
    sudo apt install libnss-libvirt
    ```
    Then edit `/etc/nsswitch.conf` and add `libvirt` to the `hosts:` line.

## 📝 License

MIT License.