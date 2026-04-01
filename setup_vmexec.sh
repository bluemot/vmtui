#!/bin/bash

# setup_vmexec.sh - vmexec.py 主機環境自動建置腳本
# 目的：自動安裝必要套件，並檢查當前使用者權限

set -e

echo "=== vmexec.py 主機環境建置腳本 ==="

# 1. 檢查是否具備 sudo 權限
if ! sudo -v &>/dev/null; then
    echo "[錯誤] 此腳本需要 sudo 權限來進行套件安裝。"
    exit 1
fi

# 2. 安裝 libvirt-clients 與相關工具
echo "[1/3] 正在安裝 libvirt-clients..."
sudo apt update -qq
sudo apt install -y -qq libvirt-clients qemu-utils

# 3. 權限檢查與設定 (libvirt 群組)
echo "[2/3] 正在檢查使用者群組..."
CURRENT_USER=$(whoami)
if groups "$CURRENT_USER" | grep -q "\blibvirt\b"; then
    echo "[OK] 使用者 $CURRENT_USER 已在 libvirt 群組中。"
else
    echo "[設定] 正在將使用者 $CURRENT_USER 加入 libvirt 群組..."
    sudo usermod -aG libvirt "$CURRENT_USER"
    echo "[提示] 設定已完成。請注意：您必須登出並重新登入，權限才會生效。"
    echo "      或者，您可以執行 'newgrp libvirt' 來在當前視窗立即生效。"
fi

# 4. 賦予 vmexec.py 執行權限
if [ -f "vmexec.py" ]; then
    echo "[3/3] 正在設定 vmexec.py 執行權限..."
    chmod +x vmexec.py
    echo "[OK] 已將 vmexec.py 設為可執行。"
fi

echo "------------------------------------------------"
echo "主機環境建置完成！"
echo ""
echo "測試方式 (請確保 VM 已開啟並已安裝 QEMU Guest Agent)："
echo "  ./vmexec.py <VM_NAME> whoami"
echo ""
echo "如果執行失敗，請參閱 vmexec_setup_guide.md 進行疑難排解。"
echo "------------------------------------------------"
