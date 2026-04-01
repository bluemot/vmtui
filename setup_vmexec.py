#!/usr/bin/env python3
import subprocess
import os
import sys
import shutil

def run_command(command, shell=False, check=True):
    try:
        subprocess.run(command, shell=shell, check=check)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: {e}")
        return False

def main():
    print("=== vmexec.py 主機環境建置腳本 (Python 版) ===")

    # 1. 檢查是否為 Linux 系統
    if sys.platform != "linux":
        print("[錯誤] 此腳本僅支援 Linux 系統。")
        sys.exit(1)

    # 2. 檢查 sudo 權限
    if os.geteuid() != 0:
        print("[提示] 腳本目前不具備 root 權限，部分操作將要求輸入密碼。")

    # 3. 安裝必要套件 (libvirt-clients)
    print("[1/3] 正在檢查並安裝主機端必要套件...")
    if shutil.which("apt"):
        run_command(["sudo", "apt", "update", "-qq"])
        run_command(["sudo", "apt", "install", "-y", "-qq", "libvirt-clients", "qemu-utils"])
    else:
        print("[警告] 未偵測到 apt 套件管理員。請手動安裝 libvirt-clients。")

    # 4. 權限檢查與設定 (libvirt 群組)
    print("[2/3] 正在檢查使用者群組權限...")
    try:
        current_user = os.environ.get("SUDO_USER") or os.environ.get("USER")
        if not current_user:
            result = subprocess.run(["whoami"], capture_output=True, text=True)
            current_user = result.stdout.strip()

        groups_res = subprocess.run(["groups", current_user], capture_output=True, text=True)
        if "libvirt" in groups_res.stdout:
            print(f"[OK] 使用者 {current_user} 已具備 libvirt 權限。")
        else:
            print(f"[設定] 正在將使用者 {current_user} 加入 libvirt 群組...")
            run_command(f"sudo usermod -aG libvirt {current_user}", shell=True)
            print("[提示] 您必須登出並重新登入，或執行 'newgrp libvirt'，權限才會生效。")
    except Exception as e:
        print(f"[錯誤] 無法設定使用者群組: {e}")

    # 5. 賦予 vmexec.py 執行權限
    vmexec_path = os.path.join(os.path.dirname(__file__), "vmexec.py")
    if os.path.exists(vmexec_path):
        print("[3/3] 正在設定 vmexec.py 執行權限...")
        os.chmod(vmexec_path, 0o755)
        print("[OK] 已完成設定。")

    print("-" * 50)
    print("建置完成！請參閱 vmexec_setup_guide.md 進行進一步的虛擬機端設定。")
    print("-" * 50)

if __name__ == "__main__":
    main()
