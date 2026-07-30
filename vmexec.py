#!/usr/bin/env python3
import subprocess
import json
import base64
import sys
import time
import readline
import os

def make_bash_cmd(user_cmd):
    """Build a bash -c command that sources .bashrc (bypassing the interactive
    guard) before executing user_cmd, so PATH/aliases from .bashrc are applied."""
    return (
        "eval \"$(awk '/^case .- in/{f=1} f&&/^esac/{f=0;next} !f && !/PS1.*return/' ~/.bashrc)\"; "
        + user_cmd
    )

def check_channel(vm_name):
    """Test if the QEMU Guest Agent channel is alive."""
    ping_cmd = [
        "virsh", "-c", "qemu:///system",
        "qemu-agent-command", vm_name,
        json.dumps({"execute": "guest-ping"})
    ]
    try:
        subprocess.check_output(ping_cmd, stderr=subprocess.STDOUT, timeout=5)
        return True
    except subprocess.TimeoutExpired:
        print(f"Error: QEMU Guest Agent on '{vm_name}' is not responding (timeout)", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as e:
        err = e.output.decode('utf-8', errors='ignore').lower()
        if "not found" in err or "does not exist" in err:
            print(f"Error: VM '{vm_name}' not found", file=sys.stderr)
        elif "agent not responding" in err or "not connected" in err or "not configured" in err:
            print(f"Error: VM '{vm_name}' is not running or QEMU Guest Agent is not installed/configured", file=sys.stderr)
        else:
            print(f"Error: Channel to VM '{vm_name}' is down - {e.output.decode('utf-8', errors='ignore').strip()}", file=sys.stderr)
        return False
    except FileNotFoundError:
        print("Error: virsh not found. Is libvirt installed?", file=sys.stderr)
        return False

def run_qemu_agent(vm_name, command_list, interactive=False):
    """Execute command inside VM via QEMU Guest Agent with streaming output."""
    exec_args = {
        "execute": "guest-exec",
        "arguments": {
            "path": command_list[0],
            "arg": command_list[1:] if len(command_list) > 1 else [],
            "capture-output": True
        }
    }
    
    cmd = ["virsh", "-c", "qemu:///system", "qemu-agent-command", vm_name, json.dumps(exec_args)]
    try:
        res = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        pid = json.loads(res)['return']['pid']
    except Exception as e:
        return f"Error: {str(e)}", 1

    status_cmd = ["virsh", "-c", "qemu:///system", "qemu-agent-command", vm_name, 
                  json.dumps({"execute": "guest-exec-status", "arguments": {"pid": pid}})]
    
    last_stdout_len = 0
    last_stderr_len = 0
    
    try:
        while True:
            res = subprocess.check_output(status_cmd)
            data = json.loads(res).get('return', {})
            
            # 取得目前的輸出
            stdout_full = base64.b64decode(data.get('out-data', '')).decode('utf-8', errors='ignore')
            stderr_full = base64.b64decode(data.get('err-data', '')).decode('utf-8', errors='ignore')
            
            # 只印出新增的部分
            if len(stdout_full) > last_stdout_len:
                print(stdout_full[last_stdout_len:], end="", flush=True)
                last_stdout_len = len(stdout_full)
            
            if len(stderr_full) > last_stderr_len:
                print(stderr_full[last_stderr_len:], end="", flush=True, file=sys.stderr)
                last_stderr_len = len(stderr_full)

            if data.get('exited'):
                return "", data.get('exitcode', 0)
            
            time.sleep(0.1)
    except KeyboardInterrupt:
        # 嘗試在離開時殺掉 VM 內的進程 (選配)
        # kill_cmd = ["virsh", "-c", "qemu:///system", "qemu-agent-command", vm_name, 
        #             json.dumps({"execute": "guest-exec", "arguments": {"path": "/usr/bin/kill", "arg": [str(pid)]}})]
        # subprocess.run(kill_cmd, capture_output=True)
        print("\n[Interrupted]")
        return "", 130

def main():
    if len(sys.argv) < 2:
        print("Usage: sudo ./vmexec.py <VM_NAME> [@USER] [COMMAND]")
        sys.exit(1)
        
    vm_name = sys.argv[1]

    if not check_channel(vm_name):
        sys.exit(1)
    
    # 互動模式 (如果沒有給 COMMAND)
    if len(sys.argv) == 2:
        history_file = os.path.expanduser("~/.vmexec_history")
        if os.path.exists(history_file):
            readline.read_history_file(history_file)
        
        print(f"Connected to {vm_name} (Interactive Mode). Press Ctrl+C to exit.")
        user_prefix = ""
        
        while True:
            try:
                prompt = f"{vm_name}# "
                cmd_line = input(prompt).strip()
                if not cmd_line: continue
                if cmd_line in ['exit', 'quit']: break
                
                # 執行指令 (預設用 root 或是之前指定的 user)
                command_list = ["/bin/bash", "-c", make_bash_cmd(cmd_line)]
                run_qemu_agent(vm_name, command_list)
                readline.write_history_file(history_file)
            except EOFError:
                break
            except KeyboardInterrupt:
                print("")
                continue
        sys.exit(0)

    raw_args = sys.argv[2:]
    # 特殊處理：如果第一個參數是 @username
    if raw_args[0].startswith('@'):
        user = raw_args[0][1:]
        command_str = " ".join(raw_args[1:])
        command_list = ["/usr/bin/sudo", "-i", "-u", user, "/bin/bash", "-c", make_bash_cmd(command_str)]
    else:
        command_str = " ".join(raw_args)
        command_list = ["/bin/bash", "-c", make_bash_cmd(command_str)]
    
    _, code = run_qemu_agent(vm_name, command_list)
    sys.exit(code)

if __name__ == "__main__":
    main()
