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

## 💿 Windows Installation Details (Important!)

Installing Windows on KVM differs from a physical machine. Please follow these steps carefully:

### Step A: Booting and Initialization

1.  Select **Create New VM** -> **Windows 10 / 11 (ISO Install)**.
2.  Enter VM Name and Disk Size (e.g., `128G`).
3.  Select your Windows ISO file.
4.  **CRITICAL**: VMTUI will launch the `virt-viewer` window. Quickly click inside the window and press any key (like Enter) to boot from CD/DVD.
    *   *If you miss this, close the window, use VMTUI "Force Stop" then "Start" to retry.*

### Step B: Loading Disk Drivers

During Windows setup, when asked "Where do you want to install Windows?", **the list will be empty**. This is normal because Windows lacks native drivers for the high-performance VirtIO controller.

Follow these steps to load the driver:

1.  Click **Load driver**.
2.  Click **Browse**.
3.  Select the **`virtio-win`** CD drive (Note: Not the Windows installation ISO).
4.  Navigate to: `amd64` -> `w10` (Use w10 for both Windows 10 and 11).
5.  Select **"Red Hat VirtIO SCSI controller"** and click Next.
6.  The disk should now appear. Continue installation.

---

## 🛠️ Windows Post-Install Setup

After installation, resolution might be low and mouse movement laggy. You need to install Guest Tools:

### 1. Install Driver Package

1.  Inside the VM, open File Explorer and go to the **`virtio-win`** CD drive.
2.  Run **`virtio-win-guest-tools.exe`**.
3.  Install everything (Next -> Finish). **Reboot the VM** when done.

### 2. Adjust Resolution & Fullscreen

After reboot:
*   **Auto-Resize**: Resize the `virt-viewer` window border, and Windows resolution will adapt automatically.
*   **Fullscreen**: Use the window menu `View` -> `Full Screen` (or press `F11`).

---

## 🐞 Common Questions & Troubleshooting

**Q: VM is slow after setup?**
A: Check if **VT-x / AMD-V** is enabled in BIOS.
Run `kvm-ok` in terminal. If it says `KVM acceleration can NOT be used`, reboot and enable virtualization in BIOS.

**Q: Cannot login to Linux VM?**
A: Default user: `ubuntu`, Password: `password`. Set automatically by Cloud-init.

**Q: Where is the shared folder?**
A:
*   **Host**: `~/driver_projects` (in your home directory).
*   **Guest (VM)**: `/home/ubuntu/host_share`.

**Q: USB Attach failed?**
A: Ensure VM is Running. Some USB 3.0 devices might need specific controllers, but most work fine for driver development.

**Q: How to SSH by Hostname (`ssh ubuntu@my-vm`)?**
A: Install `libnss-libvirt` on the Host:
```bash
sudo apt update
sudo apt install libnss-libvirt
```
Enable the module by editing `/etc/nsswitch.conf`:
```bash
sudo nano /etc/nsswitch.conf
```
Find the line starting with `hosts:`, and add `libvirt` between `files` and `dns`:
```text
hosts:          files [...] libvirt dns
```

## 📝 License

MIT License.

<br>
<br>

---
---
---

<br>
<br>

# VMTUI - KVM/QEMU 整合管理工具 (Linux & Windows)

**VMTUI** 是一個專為 Linux 開發者設計的 Python TUI (文字介面) 工具，用於輕鬆建立與管理 KVM 虛擬機。

它將 Linux Cloud-Init 自動化與 Windows ISO 安裝的最佳特性結合在一個強大的工具中。

## 🌟 核心功能

### 🐧 Linux 功能 (Cloud-Init 自動化)
*   **自動安裝**：自動下載並安裝 Ubuntu (22.04/24.04) 或 Debian 12 Cloud Image。
*   **零配置設定**：自動設定 `ubuntu` 使用者 (密碼：`password`)、SSH 存取權限與主機名稱。
*   **共享目錄**：Host 的 `~/driver_projects` 會透過高效能 **VirtioFS** 自動掛載至 Guest 的 `/home/ubuntu/host_share`。
*   **預裝套件**：包含驅動開發必備工具：`build-essential`, `linux-headers`, `wireless-tools`, `unzip`, `bear`, `samba`, `sshfs` 等。
*   **雙控制台**：支援互動式 `virsh console` 與背景 Kernel Log 檔案記錄 (`ttyS1`)。

### 🪟 Windows 功能 (ISO 支援)
*   **Windows 10/11 支援**：最佳化的 Windows ISO 安裝精靈。
*   **驅動處理**：自動處理 `virtio-win.iso` 下載並掛載，解決硬碟/網路驅動問題。
*   **TPM 2.0 與 Secure Boot**：預設啟用 (使用 `swtpm` 與 `ovmf`) 以支援 Windows 11 需求。

### ⚙️ 一般管理
*   **VM 註冊表**：透過 `vms.json` 追蹤分散在不同路徑的 VM。
*   **殭屍清理 (Zombie Cleanup)**：智慧偵測並清除衝突的 VM 狀態 (有定義但無檔案，或有檔案無定義)。
*   **USB 熱插拔**：圖形化選單，可即時掛載/卸載 Host USB 裝置。
*   **電源管理**：啟動、停止、休眠 (存至硬碟) 與暫停 (存至 RAM)。
*   **匯入/救援**：將現有的 VM 目錄匯入至管理員中。

---

## 🚀 安裝與使用

### 1. 環境需求
*   Host OS: Ubuntu 22.04 / 24.04 LTS (推薦)
*   Python 3

### 2. 設定 Host 環境
第一次執行？請使用內建的設定選項：
1.  執行 `./vmtui.py`
2.  選擇 **"1. Setup Host Environment"**
3.  這將安裝 KVM, Libvirt, VirtIO 驅動程式與其他必要套件。
4.  **重新啟動** 你的 Host 電腦。

### 3. 執行 VMTUI
```bash
chmod +x vmtui.py
sudo ./vmtui.py
```

---

## 📖 主選單指南

### 1. Setup Host Environment
安裝所有必要的相依套件 (`qemu-kvm`, `libvirt`, `virtinst`, `swtpm`, `unzip` 等) 並設定使用者權限。

### 2. Create New VM
*   **Linux Cloud Image**: 選擇 Ubuntu/Debian，設定硬碟大小，剩下的交給 VMTUI。VM 會自動重開機一次以完成設定。
*   **Windows ISO**: 指定 Windows ISO 檔。VMTUI 會自動掛載 VirtIO 驅動 ISO。

### 3. Switch Active VM
從註冊表中選擇要管理的 VM。

### 4. Console (Text Access) [Linux Only]
連線至序列控制台 (`ttyS0`)。對於 Kernel 除錯或無頭 (Headless) 操作非常有用。
*   **離開**: 按 `Ctrl + ]`
*   **登入**: `ubuntu` / `password`

### 5. Start / Restore
啟動 VM 或從休眠狀態 (managedsave) 還原。

### 6. Viewer (Graphical Access)
啟動 `virt-viewer` (SPICE/VNC) 圖形化桌面體驗。Windows 操作必備。

### 7. USB Manager
將 Host USB 裝置直通 (Pass-through) 給 VM。
*   **Attach**: 連接裝置 (如 Wifi Dongle) 到 VM。
*   **Detach**: 將裝置歸還給 Host。
*   **警告**: 在重開機 VM 之前，務必先卸載 USB 裝置，以避免 Host Kernel 死鎖。

### 8-A. Power Options
*   **Hibernate**: 將 VM 狀態存至硬碟並關機。
*   **Pause**: 將 VM 凍結在 RAM 中。
*   **Resume**: 解凍 VM。

### B. Force Stop VM
相當於拔掉電源插頭。當 VM 無回應時使用。

### D. Import / Rescue VM Directory
如果你有一個現有的 VM 資料夾 (內含 `.qcow2` 檔)，使用此功能將其註冊到 VMTUI。

---

## 💿 Windows 安裝流程詳解 (重要！)

在 KVM 上安裝 Windows 與實體機不同，請務必遵循以下步驟：

### 步驟 A：開機與初始化

1.  選擇 **Create New VM** -> **Windows 10 / 11 (ISO Install)**。
2.  輸入 VM 名稱與硬碟大小 (例如 `128G`)。
3.  選擇你的 Windows ISO 檔案。
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
3.  一路 Next 安裝到底 (全部安裝)，完成後**重新啟動 VM**。

### 2. 調整解析度與全螢幕

重開機後：

*   **自動縮放**：直接拉動 `virt-viewer` 的視窗邊緣，Windows 解析度會自動隨之調整。
*   **全螢幕**：使用視窗選單的 `View` -> `Full Screen` (或按 `F11`)。

---

## 🐞 常見問題與排除 (FAQ)

**Q: 執行 Setup 後，VM 還是跑很慢？**
A: 請確認 BIOS 中的 **VT-x / AMD-V** 虛擬化技術已開啟。
執行 `kvm-ok` 指令檢查，如果顯示 `KVM acceleration can NOT be used`，請重開機進入 BIOS 開啟虛擬化選項。

**Q: 無法登入 Linux VM？**
A: 預設使用者名稱為 `ubuntu`，密碼為 `password`。這是由 Cloud-init 在建立時自動設定的。

**Q: 共享目錄在哪裡？**
A:
*   **Host 端**：預設位於你的家目錄下 `~/driver_projects`。
*   **VM 端**：預設掛載於 `/home/ubuntu/host_share`。

**Q: USB 掛載失敗？**
A: 請確認 VM 處於 Running 狀態。部分 USB 3.0 裝置可能需要特定的 Controller 驅動，但在大多數 Linux 開發情境下可直接運作。

**Q: 如何透過 Hostname 連線 (`ssh ubuntu@my-vm`)？**
A: 在 Host 機器安裝 `libnss-libvirt` 套件：
```bash
sudo apt update
sudo apt install libnss-libvirt
```
啟用模組：編輯 `/etc/nsswitch.conf`：
```bash
sudo nano /etc/nsswitch.conf
```
找到 `hosts:` 開頭的那一行，在 `files` 和 `dns` 之間加上 `libvirt`：
```text
hosts:          files [...] libvirt dns
```
