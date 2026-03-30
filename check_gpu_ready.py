#!/usr/bin/env python3
# check_gpu_ready.py
import os
import sys
import subprocess
import glob

def print_color(msg, color="white"):
    colors = {"green": "\033[92m", "red": "\033[91m", "yellow": "\033[93m", "bold": "\033[1m", "reset": "\033[0m"}
    c = colors.get(color, colors["reset"])
    print(f"{c}{msg}{colors['reset']}")

def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, shell=True, text=True).strip()
    except:
        return ""

def check_iommu_enabled():
    print_color("\n[1] 檢查 Kernel IOMMU 設定...", "bold")
    cmdline = run_cmd("cat /proc/cmdline")
    if "intel_iommu=on" in cmdline or "amd_iommu=on" in cmdline:
        print_color("✅ IOMMU 已在 Kernel 啟動。", "green")
        return True
    else:
        print_color("❌ IOMMU 未啟動！", "red")
        print("   請編輯 /etc/default/grub，在 GRUB_CMDLINE_LINUX_DEFAULT 加入:")
        print("   Intel CPU: intel_iommu=on iommu=pt")
        print("   AMD CPU:   amd_iommu=on iommu=pt")
        print("   然後執行 sudo update-grub 並重開機。")
        return False

def list_gpus():
    print_color("\n[2] 掃描顯示卡 (GPU)...", "bold")
    lspci = run_cmd("lspci -nn | grep -iE 'vga|3d'")
    gpus = []
    for line in lspci.split('\n'):
        if not line: continue
        # Extract ID (e.g., 01:00.0) and Name
        parts = line.split(' ')
        slot_id = parts[0]
        # Check IOMMU Group
        group_path = f"/sys/bus/pci/devices/0000:{slot_id}/iommu_group"
        if os.path.exists(group_path):
            group_num = os.path.basename(os.path.realpath(group_path))
        else:
            group_num = "Unknown"
        
        print(f"   📍 Slot: {slot_id} | Group: {group_num} | {line[7:]}")
        gpus.append({'slot': slot_id, 'group': group_num, 'desc': line})
    
    if len(gpus) == 0:
        print_color("❌ 找不到顯卡？", "red")
    elif len(gpus) >= 2:
        print_color(f"✅ 偵測到 {len(gpus)} 張顯卡，適合進行 Passthrough！", "green")
    else:
        print_color("⚠️ 只偵測到 1 張顯卡。若要直通，Linux 介面將會暫時關閉 (Single GPU Passthrough)。", "yellow")
    return gpus

def check_isolation(gpus):
    print_color("\n[3] 檢查 IOMMU 分組隔離性...", "bold")
    # 簡單檢查：如果顯卡所在的 Group 裡面還有其他非相關裝置，就不能隨便直通
    for gpu in gpus:
        grp = gpu['group']
        if grp == "Unknown": continue
        
        # List all devices in this group
        devices = glob.glob(f"/sys/kernel/iommu_groups/{grp}/devices/*")
        print_color(f"\n   🔍 分析 Group {grp} (屬於 {gpu['slot']}):", "bold")
        
        clean_group = True
        for dev_path in devices:
            dev_id = os.path.basename(dev_path)[5:] # remove 0000:
            dev_info = run_cmd(f"lspci -nns {dev_id}")
            prefix = "      "
            if dev_id == gpu['slot']:
                print(f"{prefix}✅ {dev_info} (目標顯卡)")
            elif "Audio" in dev_info and dev_id.startswith(gpu['slot'][:-1]):
                print(f"{prefix}✅ {dev_info} (顯卡音效，可一起直通)")
            elif "Bridge" in dev_info:
                print(f"{prefix}⚪ {dev_info} (PCI Bridge，通常可忽略)")
            else:
                print(f"{prefix}❌ {dev_info} (干擾裝置！)")
                clean_group = False
        
        if clean_group:
            print_color("      🎉 這個 Group 很乾淨，可以直通！", "green")
        else:
            print_color("      ⚠️ 這個 Group 不乾淨，需要進行 ACS Patch 才能拆分 (進階)。", "red")

if __name__ == "__main__":
    print_color("=== KVM GPU Passthrough Readiness Check ===", "bold")
    if os.geteuid() != 0:
        print("請使用 sudo 執行此腳本以獲得完整資訊。")
        
    iommu = check_iommu_enabled()
    if iommu:
        gpus = list_gpus()
        if gpus:
            check_isolation(gpus)
    else:
        print("\n❌ 必須先啟用 IOMMU 才能進行後續檢查。")
