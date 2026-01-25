
---

# VMTUI - KVM Driver Development Environment Manager (Ultimate Edition)

**VMTUI** 是一個專為 Linux Driver 開發者設計的 Python TUI (Text User Interface) 工具。它將繁瑣的 KVM/QEMU 指令、虛擬機還原、USB 裝置直通 (Passthrough) 等功能整合為簡單的圖形化選單。

本版本經過深度優化，解決了 USB 死鎖、Console 黑屏、多 VM 管理等常見痛點，並整合了 VNC 圖形介面以支援舊版 Kernel 除錯。

## 🌟 核心功能特色 (New!)

1. **多 VM 獨立管理**：採用目錄隔離機制 (`vms/<vm_name>/`)，每個 VM 擁有獨立的 Image、Log 與設定檔，互不干擾，刪除方便。
2. **雙軌 Log 機制**：
* **Interactive Console (`ttyS0`)**：供 `virsh console` 登入操作。
* **File Log (`ttyS1`)**：將 Kernel Log 即時寫入 Host 檔案，VM 死當也能查 Log。


3. **VNC 圖形救援**：預設開啟 VNC (Port 5900) 與 QXL 顯卡，解決舊版 Kernel (如 5.14) 在無頭模式 (Headless) 下初始化失敗的問題。
4. **USB 安全掛載**：提供圖形化 USB Attach/Detach 選單，防止重開機死鎖。
5. **自我提權 (Self-Elevation)**：直接執行腳本即可，程式會自動呼叫 `sudo`。
6. **開發者友善**：預設開啟 `VirtioFS` 共享目錄 (Host 與 Guest 秒級同步) 與 `KGDB` 除錯通道。

## 📂 專案目錄結構

VMTUI 會自動在當前目錄下建立 `vms/` 資料夾來管理所有虛擬機：

```text
.
├── vmtui.py              # 主程式
├── vms/                  # VM 儲存庫 (自動產生)
│   ├── driver-dev-vm/    # VM 1 專屬目錄
│   │   ├── driver-dev-vm.qcow2       # 虛擬硬碟
│   │   ├── driver-dev-vm-console.log # Kernel Log (除錯用)
│   │   ├── user-data                 # Cloud-init 設定
│   │   └── seed.iso
│   └── vm24/             # VM 2 專屬目錄
│       └── ...
└── README.md

```

## 🚀 安裝與執行

### 1. 準備環境

Host 建議使用 **Ubuntu 22.04 LTS** 或 **24.04 LTS**。本腳本僅需系統內建 Python 3。

### 2. 給予執行權限 (首次執行)

```bash
chmod +x vmtui.py

```

### 3. 執行

不用打 sudo，像帥氣的駭客一樣直接執行：

```bash
./vmtui.py

```

---

## 📖 選單功能詳解

啟動後，你將看到以下主選單：

### 1. Setup Host Environment (建立 Host 環境)

* **功能**：檢查並安裝 KVM, Libvirt, virtiofsd 等必要套件。
* **注意**：執行完畢後，**強烈建議重開機** 以確保群組權限生效。

### 2. Create / Reset VM (建立/重置 VM)

* **功能**：建立全新的 VM。
* **防呆機制**：如果目錄已存在或 VM 未清除乾淨 (Zombie)，會跳出警告視窗詢問是否覆蓋。
* **自動重啟**：VM 安裝完成後會**自動重開機**一次，以確保 GRUB 的 Console 參數正確生效。

### 3. USB Manager (USB 裝置管理)

* **功能**：列出 Host 上的 USB 裝置，按 Enter 鍵切換 **[ATTACHED]** (掛載) 或 **[FREE]** (卸載) 狀態。
* **⚠️ 重要安全守則**：**在對 VM 執行 `reboot` 或 `poweroff` 之前，務必先 Detach 所有 USB 裝置，否則 Host Kernel 可能會死鎖！**

### 4. Console (進入文字終端)

* **功能**：連線至 `ttyS0` 進行操作。
* **卡住怎麼辦？**：如果畫面一片黑，請按一下 **Enter** 鍵喚醒登入提示。
* **離開方法**：按下 `Ctrl + ]`。

### 5~8. Power Management (電源管理)

* **Start**: 啟動 VM。
* **Hibernate**: 休眠至硬碟 (Managed Save)，釋放記憶體。
* **Pause/Resume**: 暫停至 RAM (Suspend)。

### 9. Force Stop (強制斷電)

* **功能**：相當於拔掉電源線 (`virsh destroy`)。當 VM 死當無法回應時使用。

### A. Switch Active VM (切換當前 VM)

* **功能**：自動掃描 `vms/` 資料夾，列出所有已建立的專案供您切換。

---

## 🔧 進階除錯指南

### 1. 如何查看開機 Log (當 Console 黑屏時)

如果 VM 開不起來，且 Console 沒反應，請檢查 Host 上的實體 Log 檔案：

```bash
# 預設路徑在該 VM 的目錄下
tail -f vms/<vm_name>/<vm_name>-console.log

```

*權限說明：Log 檔已自動修正為 `libvirt-qemu:kvm`，您的使用者帳號可直接讀取。*

### 2. 如何使用 VNC 圖形介面 (終極大招)

當 Serial Console 完全失效 (例如 Kernel Panic 導致連 Log 都吐不出來)，請使用 VNC 查看「真實螢幕」。

* **VNC Client**: 請安裝 RealVNC Viewer 或 TigerVNC。
* **連線地址**: `Host_IP:5900` (例如 `192.168.1.100:5900` 或 `localhost:5900`)。
* **預設密碼**: `123456`
* **用途**: 可以看到 GRUB 選單、BIOS 畫面以及 Kernel Panic 的 Call Trace。

### 3. SSH 免密碼連線

在 Host 安裝名稱解析服務，即可直接用 Hostname 連線：

```bash
sudo apt install libnss-libvirt
# 之後即可直接連線，不需查 IP
ssh ubuntu@driver-dev-vm

```

---

## ☠️ 踩坑地圖 (Troubleshooting Map)

**這是一張用血淚換來的地圖，遇到問題請先查閱此處。**

| 症狀 (Symptom) | 可能原因 (Cause) | 解決方案 (Solution) |
| --- | --- | --- |
| **重開機死鎖 (Deadlock)**<br>

<br>VM 卡死，Host `virsh` 指令無回應，需強制重開機。 | **USB 裝置未卸載！**<br>

<br>VM 重置硬體時，掛載的 USB 導致 Host Kernel 鎖死。 | **拔管再重開**。<br>

<br>重開 VM 前，務必在 VMTUI USB 選單中 **Detach** 裝置。 |
| **Console 黑屏**<br>

<br>選單 4 進去後按 Enter 沒反應，Log 檔也是空的。 | **Kernel 初始化失敗**<br>

<br>常見於舊 Kernel (5.14) 不支援 Q35 新架構，卡在 Early Boot。 | 1. 使用 **VNC Viewer** 連線 Port 5900 查看報錯。<br>

<br>2. 若是 Kernel 太舊，考慮換回 `pc` (i440fx) 架構。 |
| **幽靈 VM (Zombie)**<br>

<br>手動刪了目錄，但重建時說 VM 已存在。 | **Libvirt 殘留設定**<br>

<br>只刪了檔案但沒註銷 VM。 | 使用 VMTUI 的 **Create/Reset** 功能，它會自動偵測並清除殘留設定。 |
| **AppArmor / Permission Denied**<br>

<br>無法啟動 VM 或存取 Log。 | **Snap 沙盒衝突**<br>

<br>您可能在使用 Snap 版的 Zellij/Tmux。 | 改用 Apt 安裝終端機工具，或在純 Bash 下執行。 |
| **Kernel Panic (Ubuntu 24.04)**<br>

<br>開機直接當掉。 | **版本不相容**<br>

<br>Ubuntu 24.04 的 User Space 不支援過舊的 Kernel (如 5.14)。 | 若需開發舊 Driver，請在建立 VM 時選擇 **Ubuntu 22.04** 或 **Debian 12**。 |

---

## 📝 License

MIT License. Feel free to use for your driver development!

## 🛠️ 常見問題與排除
Q: 執行 Setup 後，VM 還是跑很慢？  
A: 請確認 BIOS 中的 VT-x / AMD-V 虛擬化技術已開啟。 執行 kvm-ok 指令檢查，如果顯示 KVM acceleration can NOT be used，請重開機進入 BIOS 開啟虛擬化選項。

Q: 無法登入 VM？  
A: 預設使用者名稱為 ubuntu，密碼為 password。這是由 Cloud-init 在建立時自動設定的。

Q: 共享目錄在哪裡？  
A: * Host 端：預設位於你的家目錄下 ~/driver_projects。

VM 端：預設掛載於 /mnt/host_share。

Q: USB 掛載失敗？  
A: 請確認 VM 處於 Running 狀態。部分 USB 3.0 裝置可能需要特定的 Controller 驅動，但在大多數 Linux 開發情境下可直接運作。

Q:如何透過ssh -l $vm_user $vm_host_name 就連進vm？  
A: 在host機器安裝 libnss-libvirt 套件
```bash
sudo apt update
sudo apt install libnss-libvirt
```
啟用模組： 編輯 /etc/nsswitch.conf：
```bash
sudo nano /etc/nsswitch.conf
````
找到 hosts: 開頭的那一行，在 files 和 dns 之間（或者最後面）加上 libvirt。  
修改前：
```text
hosts:          files [...] dns
````
修改後：
```text
hosts:          files [...] libvirt dns
````



---

# WinVMTUI - Windows KVM Manager

**WinVMTUI** 是一個專為 Linux Host 設計的 Python TUI 工具，用於簡化 Windows 10/11 虛擬機在 KVM/QEMU 上的安裝與管理。

它解決了在 Linux 上安裝 Windows VM 最頭痛的幾個問題：

1. **驅動掛載**：自動下載並掛載 `virtio-win.iso`，解決安裝時找不到硬碟的問題。
2. **Windows 11 支援**：自動配置 TPM 2.0 (swtpm)、UEFI (OVMF) 與 Q35 晶片組。
3. **開機引導**：透過自動暫停 (Auto-Pause) 機制，讓你不會錯過 "Press any key to boot from CD" 的畫面。
4. **權限修復**：自動處理 `libvirt-qemu` 無法讀取 ISO 或家目錄的權限問題 (ACL)。

---

## 📋 系統需求

* **OS**: Ubuntu 22.04 / 24.04, Debian 12 (Host OS)
* **Python**: Python 3.6+
* **權限**: 需要 `sudo` 權限來管理 KVM 與網路。
* **ISO**: 請自行準備微軟官方的 Windows 10 或 11 ISO 映像檔。

## 🚀 快速開始

### 1. 下載與執行

不需要安裝額外的 Python 套件，直接下載腳本並執行：

```bash
# 賦予執行權限 (可選)
chmod +x winvmtui.py

# 必須使用 sudo 執行
sudo python3 winvmtui.py

```

### 2. 主選單功能

程式啟動後，你將看到以下選單：

1. **Setup Host (Install OVMF/TPM)**
* **首次使用必點**。會自動安裝 `qemu-kvm`, `virt-manager`, `swtpm` (TPM 模擬), `ovmf` (UEFI BIOS) 等必要套件，並設定網路。
* *注意：安裝完後建議重開機一次。*


2. **Create Windows VM**
* 引導式建立 VM。支援自訂名稱、硬碟大小，並內建檔案瀏覽器選擇 ISO。


3. **Open Desktop Viewer**
* 開啟 `virt-viewer` 視窗連線到目前的 VM。


4. **Force Stop VM**
* 強制關閉 VM (拔電源)，用於安裝失敗或當機時。



---

## 💿 安裝流程詳解 (重要！)

Windows 在 KVM 上的安裝與一般實體機不同，請務必閱讀以下步驟：

### 步驟 A：建立 VM 與開機引導

1. 選擇 **Create Windows VM**。
2. 依序輸入 VM 名稱與硬碟大小 (例如 `128G`)。
3. 在選單中找到你的 Windows ISO 檔案。
4. **關鍵時刻**：腳本會啟動 VM 並**立即暫停 (Pause)**，同時彈出 `virt-viewer` 視窗。
* 這是為了讓你準備好按鍵，以免錯過 Windows 的光碟開機提示。


5. 確認視窗彈出後，點擊視窗內部，準備好你的鍵盤 (空白鍵或 Enter)。
6. 回到終端機按下 **Enter** 恢復 VM，然後迅速在視窗內按鍵進入安裝程式。

### 步驟 B：載入硬碟驅動 (Load Driver)

在 Windows 安裝畫面選擇安裝位置時，你會發現**列表是空的 (找不到硬碟)**。這是正常的！因為 Windows 原生不支援高效能的 VirtIO 控制器。

請依照以下步驟手動載入驅動：

1. 點選左下角的 **載入驅動程式 (Load Driver)**。
2. 點選 **瀏覽 (Browse)**。
3. 選擇光碟機 **`virtio-win`** (注意：不是 Windows 安裝光碟)。
4. 路徑：`amd64` -> `w10` (Windows 10/11 都選這個)。
5. 選擇出現的 **"Red Hat VirtIO SCSI controller"** 並點擊下一步。
6. 現在硬碟應該就會出現了！繼續安裝即可。

---

## 🛠️ 安裝後設定 (Post-Install)

安裝完成並進入 Windows 桌面後，解析度可能會很低，且滑鼠移動不順暢。請執行以下步驟安裝 Guest Tools：

### 1. 安裝驅動包

1. 在 VM 內打開檔案總管，進入 **`virtio-win`** 光碟機。
2. 執行 **`virtio-win-guest-tools.exe`**。
3. 一路 Next 安裝到底，完成後**重新啟動 VM**。

### 2. 調整解析度與全螢幕

重開機後：

* **自動縮放**：直接拉動 `virt-viewer` 的視窗邊緣，Windows 解析度會自動隨之調整。
* **全螢幕**：點選視窗選單的 `View` -> `Full Screen` (或按 `F11`)。

---

## ❓ 常見問題

**Q: 出現 "No bootable device" 錯誤？**
A: 這通常是因為錯過了 "Press any key to boot from CD..." 的時機。

* 請使用腳本的 **暫停/恢復** 機制。
* 或者在開機時瘋狂按 **`Esc`** 進入 BIOS 選單，手動選擇從 DVD/CDROM 開機。

**Q: 出現 "unable to connect to libvirt"？**
A: 請確認你有使用 `sudo` 執行腳本。如果剛安裝完 Host 環境，請嘗試重開機或執行 `sudo systemctl start libvirtd`。

**Q: 安裝時找不到硬碟？**
A: 請參考上方的 [步驟 B：載入硬碟驅動](https://www.google.com/search?q=%23%E6%AD%A5%E9%A9%9F-b%E8%BC%89%E5%85%A5%E7%A1%AC%E7%A2%9F%E9%A9%85%E5%8B%95-load-driver)，這是 KVM 安裝 Windows 的必經之路。