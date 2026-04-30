import { exec, spawn, spawnSync } from 'child_process';
import { promisify } from 'util';
import * as winston from 'winston';
import * as fs from 'fs/promises';
import { createWriteStream } from 'fs';
import * as path from 'path';
import axios from 'axios';

const execAsync = promisify(exec);

export async function downloadFile(url: string, filename: string, onProgress?: (percent: number) => void): Promise<void> {
    const { data, headers } = await axios({
        url,
        method: 'GET',
        responseType: 'stream'
    });
    const contentLength = headers['content-length'];
    const totalLength = typeof contentLength === 'string' ? parseInt(contentLength, 10) : 0;
    let downloadedLength = 0;

    const writer = createWriteStream(filename);

    return new Promise((resolve, reject) => {
        data.on('data', (chunk: Buffer) => {
            downloadedLength += chunk.length;
            if (onProgress && totalLength) {
                onProgress(downloadedLength / totalLength);
            }
        });
        data.pipe(writer);
        writer.on('finish', resolve);
        writer.on('error', reject);
    });
}


async function getSudoPass(): Promise<string | null> {
    try {
        const pass = await fs.readFile('.sudo_pass', 'utf-8');
        return pass.trim();
    } catch {
        return null;
    }
}

export const logger = winston.createLogger({
    level: 'debug',
    format: winston.format.combine(
        winston.format.timestamp(),
        winston.format.json()
    ),
    transports: [
        new winston.transports.File({ filename: 'vmtui.log' })
    ]
});

export async function runCmd(cmd: string | string[], options: { shell?: boolean | string, check?: boolean, useSudo?: boolean } = {}): Promise<string | null> {
    try {
        let command = Array.isArray(cmd) ? cmd.join(' ') : cmd;
        
        if (options.useSudo) {
            const sudoPass = await getSudoPass();
            if (sudoPass) {
                command = `echo "${sudoPass}" | sudo -S ${command}`;
            } else {
                command = `sudo ${command}`;
            }
        }

        logger.debug(`Executing: ${command.replace(/echo ".*" \| sudo/g, 'echo "****" | sudo')}`);
        const result = await execAsync(command, { shell: options.shell ?? true, encoding: 'utf8' } as any);
        const stdout = result.stdout as unknown as string;
        const stderr = result.stderr as unknown as string;
        if (stderr && !stderr.includes('[sudo] password for')) {
            logger.warn(`Cmd stderr: ${stderr.trim()}`);
        }
        return stdout.trim();
    } catch (e: any) {
        logger.error(`Command execution failed: ${cmd}, Error: ${e.message}`);
        if (options.check) throw e;
        return null;
    }
}

export function spawnDetached(cmd: string, args: string[], useSudo: boolean = false) {
    let finalCmd = cmd;
    let finalArgs = args;

    if (useSudo && process.env.SUDO_USER) {
        finalCmd = 'sudo';
        finalArgs = ['-E', '-u', process.env.SUDO_USER, cmd, ...args];
    } else if (useSudo) {
        finalCmd = 'sudo';
        finalArgs = [cmd, ...args];
    }

    const child = spawn(finalCmd, finalArgs, {
        detached: true,
        stdio: 'ignore'
    });
    child.unref();
}

export function runInteractive(cmd: string, args: string[]): void {
    spawnSync(cmd, args, { stdio: 'inherit' });
}

export interface VmState {
    name: string;
    state: string;
}

export async function fixPermissions(paths: string[]): Promise<void> {
    const qemuUser = "libvirt-qemu";
    // Using runCmd for setfacl
    await runCmd(`setfacl -m u:${qemuUser}:x ${path.join('/home', process.env.SUDO_USER || 'root')}`, { useSudo: true, check: false });
    for (const p of paths) {
        if (!p) continue;
        const isDir = (await fs.stat(p)).isDirectory();
        if (isDir) {
            await runCmd(`setfacl -R -m u:${qemuUser}:rx ${p}`, { useSudo: true, check: false });
        } else {
            await runCmd(`setfacl -m u:${qemuUser}:r ${p}`, { useSudo: true, check: false });
            const parent = path.dirname(p);
            await runCmd(`setfacl -m u:${qemuUser}:x ${parent}`, { useSudo: true, check: false });
        }
    }
}

export async function createLinuxCloudVM(name: string, vmDir: string, diskPath: string, diskSize: string, imgData: any, hostShareDir: string): Promise<void> {
    const cacheDir = path.join(path.dirname(vmDir), "base_images");
    await fs.mkdir(cacheDir, { recursive: true });
    const baseImg = path.join(cacheDir, imgData.file);

    if (!(await fs.access(baseImg).then(() => true).catch(() => false))) {
        await downloadFile(imgData.url, baseImg);
    }

    await runCmd(`qemu-img create -f qcow2 -F qcow2 -b ${baseImg} ${diskPath} ${diskSize}`);
    if (process.env.SUDO_USER) {
        await runCmd(`chown ${process.env.SUDO_USER}:${process.env.SUDO_USER} ${diskPath}`, { useSudo: true });
    }

    const userDataPath = path.join(vmDir, "user-data");
    const metaDataPath = path.join(vmDir, "meta-data");
    const seedIsoPath = path.join(vmDir, "seed.iso");
    const logPath = path.join(vmDir, `${name}-console.log`);

    // Basic user-data (simplified for now)
    const userData = `#cloud-config
hostname: ${name}
manage_etc_hosts: true
ssh_pwauth: true
package_update: true
users:
  - name: ubuntu
    sudo: ALL=(ALL) NOPASSWD:ALL
    groups: users, admin
    shell: /bin/bash
    lock_passwd: false
chpasswd:
  list: |
    ubuntu:password
  expire: False
runcmd:
  - mkdir -p /home/ubuntu/host_share
  - chown ubuntu:ubuntu /home/ubuntu/host_share
  - echo "host_share /home/ubuntu/host_share virtiofs defaults 0 0" >> /etc/fstab
  - mount -a
`;

    await fs.writeFile(userDataPath, userData);
    await fs.writeFile(metaDataPath, `instance-id: ${name}\nlocal-hostname: ${name}\n`);
    await runCmd(`cloud-localds ${seedIsoPath} ${userDataPath} ${metaDataPath}`);

    await fixPermissions([diskPath, seedIsoPath, vmDir]);

    const cmd = [
        "virt-install", "--connect", "qemu:///system",
        `--name=${name}`, "--memory=12288", "--vcpus=4",
        "--memorybacking", "source.type=memfd,access.mode=shared",
        `--disk=path=${diskPath},device=disk,bus=virtio`,
        `--disk=path=${seedIsoPath},device=cdrom`,
        `--os-variant=${imgData.variant}`,
        "--import",
        "--graphics", "spice,listen=127.0.0.1", "--video", "vga",
        "--channel", "spicevmc",
        "--channel", "unix,target.type=virtio,name=org.qemu.guest_agent.0",
        "--serial", "pty", 
        "--serial", `file,path=${logPath}`,
        "--console", "pty,target_type=serial",
        `--filesystem`, `source=${hostShareDir},target=host_share,driver.type=virtiofs,accessmode=passthrough`,
        "--cpu", "host-passthrough",
        "--noautoconsole",
        "--network", "network=default,model=virtio"
    ];

    await runCmd(cmd.join(' '), { useSudo: true });
}

export interface UsbDevice {
    vid: string;
    pid: string;
    name: string;
    attached: boolean;
}

export async function getUsbDevices(vmName: string): Promise<UsbDevice[]> {
    const devices: UsbDevice[] = [];
    const lsusb = await runCmd("lsusb", { shell: true, check: false });
    const xml = await runCmd(`virsh -c qemu:///system dumpxml ${vmName}`, { useSudo: true, check: false }) || "";

    if (lsusb) {
        const lines = lsusb.split('\n');
        for (const line of lines) {
            const match = line.match(/ID ([0-9a-fA-F]+):([0-9a-fA-F]+) (.+)/);
            if (match) {
                const vid = match[1];
                const pid = match[2];
                const name = match[3];
                const attached = xml.includes(`vendor id='0x${vid}'`) && xml.includes(`product id='0x${pid}'`);
                devices.push({ vid, pid, name, attached });
            }
        }
    }
    return devices;
}

export async function toggleUsbDevice(vmName: string, device: UsbDevice): Promise<void> {
    const action = device.attached ? 'detach-device' : 'attach-device';
    const xmlContent = `<hostdev mode='subsystem' type='usb' managed='yes'><source><vendor id='0x${device.vid}'/><product id='0x${device.pid}'/></source></hostdev>`;
    const tmpXml = `/tmp/vmtui_usb_${device.vid}_${device.pid}.xml`;
    await fs.writeFile(tmpXml, xmlContent);
    await runCmd(`virsh -c qemu:///system ${action} ${vmName} ${tmpXml} --live`, { useSudo: true });
}

export async function defineVm(xmlPath: string): Promise<void> {
    await runCmd(`virsh -c qemu:///system define ${xmlPath}`, { useSudo: true, check: true });
}

export async function tailLog(logPath: string): Promise<void> {
    if (!(await fs.access(logPath).then(() => true).catch(() => false))) {
        throw new Error(`Log file not found: ${logPath}`);
    }
    runInteractive('tail', ['-f', logPath]);
}

export async function getVmStates(): Promise<Record<string, string>> {
    const states: Record<string, string> = {};
    const res = await runCmd("virsh -c qemu:///system list --all", { shell: true, check: false });
    if (res) {
        const lines = res.split('\n');
        for (const line of lines) {
            const parts = line.trim().split(/\s+/);
            if (parts.length >= 3 && parts[0] !== "Id") {
                const vmName = parts[1];
                if (vmName) {
                    const vmState = parts.slice(2).join(' ');
                    states[vmName] = vmState;
                }
            }
        }
    }
    return states;
}

export async function checkSystemHealth(): Promise<boolean> {
    const res = await runCmd("systemctl list-unit-files libvirtd.service", { shell: true, check: false });
    if (!res || !res.includes("libvirtd.service")) {
        return false;
    }

    const activeRes = await runCmd("systemctl is-active libvirtd", { shell: true, check: false });
    if (activeRes !== "active") {
        await runCmd("systemctl start libvirtd", { shell: true, check: false });
    }

    const netState = await runCmd("virsh -c qemu:///system net-info default | grep Active", { shell: true, check: false });
    if (!netState || !netState.includes("yes")) {
        await runCmd("virsh -c qemu:///system net-start default", { shell: true, check: false });
        await runCmd("virsh -c qemu:///system net-autostart default", { shell: true, check: false });
    }
    return true;
}
