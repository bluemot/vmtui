# VMTUI - KVM Driver Development Environment Manager

**VMTUI** 是一個專為 Linux Driver 開發者設計的 Python TUI (Text User Interface) 工具。它將繁瑣的 KVM/QEMU 指令、虛擬機還原、USB 裝置直通 (Passthrough) 等功能整合為簡單的選單式介面。

本工具整合了以下原始腳本的功能：
* Host 環境建置 (`01_setup_host.sh`)
* VM 自動化建置 (`02_create_driver_vm.sh`)
* USB 熱插拔管理 (`attach_detach_usb.sh`)

## 📋 功能特色

1.  **一鍵環境建置**：自動安裝 KVM、Libvirt 與必要套件，並設定使用者權限。
2.  **VM 快速重置/切換**：支援 Ubuntu 24.04/22.04 與 Debian 12，自動設定 Cloud-init (預設帳密) 與 Serial Console。
3.  **USB 熱插拔管理**：圖形化選單列出 Host 裝置，一鍵掛載 (Attach) 或卸載 (Detach) 給 VM 使用。
4.  **開發者友善**：預設開啟 `VirtioFS` 共享目錄 (Host 與 Guest 秒級同步) 與 `KGDB` 除錯通道。

## 🚀 安裝與執行

### 1. 準備檔案
請確保 `vmtui.py` 已下載至你的 Host 機器（建議為 Ubuntu 22.04/24.04）。本腳本不需額外安裝 pip 套件，使用系統內建 Python 3 即可執行。

### 2. 執行 (需要 Root 權限)
因為涉及 KVM 與網路介面操作，請務必使用 `sudo`：

```bash
sudo python3 vmtui.py
```


## 📖 選單功能說明
啟動後，你將看到以下主選單：
```text
Status: Running / Not Found

1.  Setup Host Environment
2.  Create / Reset VM (Select Image & Name)
3.  USB Manager
4.  Console
5.  Start VM
6.  Stop VM (Force)
S.  Switch Active VM
Q.  Quit
```

## 1. Setup Host Environment (建立 Host 環境)  
功能：檢查並安裝 qemu-kvm, libvirt, virtiofsd, cloud-image-utils 等必要套件。

權限：將當前使用者加入 kvm 與 libvirt 群組。

注意：執行完畢後，強烈建議重開機 以確保群組權限生效。  

## 2. Create / Reset VM (建立或重置 VM)
功能：下載 Cloud Image 並建立全新的虛擬機環境。

流程：

輸入 VM 名稱 (預設為 driver-dev-vm)。

選擇 OS 版本 (支援 Ubuntu 24.04, 22.04, Debian 12 或自訂 URL)。

腳本會自動執行以下配置：

建立 QCOW2 磁碟 (Copy-on-Write)。

產生 user-data 設定檔 (預設帳號: ubuntu, 密碼: password)。

設定 console=ttyS0 以支援 Kernel Log 輸出。

設定 virtiofs 掛載 Host 的 ~/driver_projects 目錄至 VM 的 /mnt/host_share。  

## 3. USB Manager (USB 裝置管理)
功能：自動掃描 lsusb，並允許你將裝置「直通 (Passthrough)」給 VM。

操作：

Attach (A)：產生 XML 並掛載裝置至 VM。

Detach (D)：將裝置歸還給 Host。

狀態顯示：已掛載的裝置會顯示綠色的 [ATTACHED]。  

## 4. Console (進入終端機)
功能：連線至 VM 的 Serial Console (virsh console)。

用途：查看開機訊息、Kernel Panic Log，或登入操作。

離開方法：按下 Ctrl + ] 即可跳出 Console 回到選單。  

## 5 & 6. Start / Stop VM
Start：啟動 VM。

Stop (Force)：強制斷電 (virsh destroy)，用於 Kernel 當機無法回應時。  

## S. Switch Active VM (切換當前 VM)
功能：如果你有多個 VM 專案 (例如 vm-usb-test, vm-net-test)，可在此切換「當前操作目標」。

用途：所有的建立、USB 掛載、Console 連線都會針對此處選定的 VM 進行。  

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