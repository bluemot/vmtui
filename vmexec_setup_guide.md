# vmexec.py 環境建置指引

`vmexec.py` 是一個透過 QEMU Guest Agent 在虛擬機 (VM) 內部執行指令的工具。為了確保其正常運作，您需要完成以下主機端與虛擬機端的設定。

## 1. 主機端 (Host) 設定

### 安裝必要套件
確保主機已安裝 `libvirt-clients`：
```bash
sudo apt update
sudo apt install -y libvirt-clients
```

### 權限設定
`vmexec.py` 預設使用 `qemu:///system` 連線。建議將您的使用者加入 `libvirt` 群組，以避免每次都需要使用 `sudo`：
```bash
sudo usermod -aG libvirt $USER
# 執行完畢後請登出並重新登入，或執行 'newgrp libvirt'
```

## 2. 虛擬機端 (Guest) 設定

### 安裝 QEMU Guest Agent
在虛擬機內部（Linux），請安裝並啟動 `qemu-guest-agent`：
```bash
sudo apt update
sudo apt install -y qemu-guest-agent
sudo systemctl enable --now qemu-guest-agent
```

### 確認虛擬機配置 (XML)
虛擬機必須具備 QEMU Guest Agent 的通訊通道。如果您的 VM 不是透過 `vmtui` 建立的，請檢查其 XML 設定：
```bash
virsh edit <VM_NAME>
```
確保 `<devices>` 區段內包含以下內容：
```xml
<channel type='unix'>
  <target type='virtio' name='org.qemu.guest_agent.0'/>
  <address type='virtio-serial' controller='0' bus='0' port='1'/>
</channel>
```

## 3. 測試連線
在主機端執行以下指令測試是否能成功溝通：
```bash
virsh qemu-agent-command <VM_NAME> '{"execute":"guest-ping"}'
```
如果回傳 `{"return":{}}`，代表連線成功。

## 4. 使用 vmexec.py

### 互動模式
```bash
./vmexec.py <VM_NAME>
```

### 直接執行指令
```bash
./vmexec.py <VM_NAME> ls -la /home/ubuntu
```

### 切換使用者執行
```bash
./vmexec.py <VM_NAME> @ubuntu whoami
```
