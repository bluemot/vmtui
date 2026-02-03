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

## 💿 Windows 安裝流程詳解 (重要！)

Windows 在 KVM 上的安裝與一般實體機不同，請務必閱讀以下步驟：

### 步驟 A：建立 VM 與開機引導

1.  選擇 **Create New VM** -> **Windows 10 / 11 (ISO Install)**。
2.  依序輸入 VM 名稱與硬碟大小 (例如 `128G`)。
3.  在選單中找到你的 Windows ISO 檔案。
4.  **關鍵時刻**：VMTUI 會啟動 `virt-viewer` 視窗。請迅速點擊視窗內部，並按下任意鍵 (如 Enter) 以從 CD/DVD 開機。
    *   *如果錯過了，請關閉視窗，使用 VMTUI 的 "Force Stop" 然後 "Start" 重試。*

### 步驟 B：載入硬碟驅動 (Load Driver)

在 Windows 安裝畫面選擇安裝位置時，你會發現**列表是空的 (找不到硬碟)**。這是正常的！因為 Windows 原生不支援高效能的 VirtIO 控制器。

請依照以下步驟手動載入驅動：

1.  點選左下角的 **載入驅動程式 (Load Driver)**。
2.  點選 **瀏覽 (Browse)**。
3.  選擇光碟機 **`virtio-win`** (注意：不是 Windows 安裝光碟)。
4.  路徑：`amd64` -> `w10` (Windows 10/11 都選這個)。
5.  選擇出現的 **"Red Hat VirtIO SCSI controller"** 並點擊下一步。
6.  現在硬碟應該就會出現了！繼續安裝即可。

---

## 🛠️ Windows 安裝後設定 (Post-Install)

安裝完成並進入 Windows 桌面後，解析度可能會很低，且滑鼠移動不順暢。請執行以下步驟安裝 Guest Tools：

### 1. 安裝驅動包

1.  在 VM 內打開檔案總管，進入 **`virtio-win`** 光碟機。
2.  執行 **`virtio-win-guest-tools.exe`**。
3.  一路 Next 安裝到底，完成後**重新啟動 VM**。

### 2. 調整解析度與全螢幕

重開機後：

*   **自動縮放**：直接拉動 `virt-viewer` 的視窗邊緣，Windows 解析度會自動隨之調整。
*   **全螢幕**：點選視窗選單的 `View` -> `Full Screen` (或按 `F11`)。

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

---

## 🛠️ 常見問題與排除 (FAQ in Chinese)

**Q: 執行 Setup 後，VM 還是跑很慢？**
A: 請確認 BIOS 中的 **VT-x / AMD-V** 虛擬化技術已開啟。
執行 `kvm-ok` 指令檢查，如果顯示 `KVM acceleration can NOT be used`，請重開機進入 BIOS 開啟虛擬化選項。

**Q: 無法登入 VM？**
A: 預設使用者名稱為 `ubuntu`，密碼為 `password`。這是由 Cloud-init 在建立時自動設定的。

**Q: 共享目錄在哪裡？**
A:
*   **Host 端**：預設位於你的家目錄下 `~/driver_projects`。
*   **VM 端**：預設掛載於 `/home/ubuntu/host_share` (舊版為 `/mnt/host_share`)。

**Q: USB 掛載失敗？**
A: 請確認 VM 處於 Running 狀態。部分 USB 3.0 裝置可能需要特定的 Controller 驅動，但在大多數 Linux 開發情境下可直接運作。

**Q: 如何透過 `ssh ubuntu@<vm-name>` 直接連線 (免查 IP)？**
A: 在 Host 機器安裝 `libnss-libvirt` 套件：
```bash
sudo apt update
sudo apt install libnss-libvirt
```
啟用模組：編輯 `/etc/nsswitch.conf`：
```bash
sudo nano /etc/nsswitch.conf
```
找到 `hosts:` 開頭的那一行，在 `files` 和 `dns` 之間加上 `libvirt`。
修改前：
```text
hosts:          files [...] dns
```
修改後：
```text
hosts:          files [...] libvirt dns
```