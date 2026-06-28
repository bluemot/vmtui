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


let cachedSudoPass: string | null = null;

async function getSudoPass(): Promise<string | null> {
    if (cachedSudoPass !== null) {
        return cachedSudoPass;
    }
    try {
        const pass = await fs.readFile('.sudo_pass', 'utf-8');
        cachedSudoPass = pass.trim();
        return cachedSudoPass;
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

export function setSudoPass(pass: string): void {
    cachedSudoPass = pass;
}

export function isRoot(): boolean {
    return typeof process.getuid === 'function' && process.getuid() === 0;
}

export async function checkSudoNoPassword(): Promise<boolean> {
    try {
        await runCmd('sudo -n true', { shell: true, check: true });
        return true;
    } catch {
        return false;
    }
}

export async function validateSudoPass(pass: string): Promise<boolean> {
    try {
        await execAsync(`echo "${pass}" | sudo -S true`, { shell: true } as any);
        return true;
    } catch {
        return false;
    }
}

export async function initSudoAuth(pass: string): Promise<boolean> {
    const valid = await validateSudoPass(pass);
    if (valid) {
        cachedSudoPass = pass;
        try {
            await execAsync(`echo "${pass}" | sudo -S -v`, { shell: true } as any);
        } catch {
            // -v may fail on some systems; cache is still enough for runCmd
        }
    }
    return valid;
}

export function spawnDetached(cmd: string, args: string[], useSudo: boolean = false) {
    let finalCmd = cmd;
    let finalArgs = args;
    const env: Record<string, string | undefined> = {};

    if (useSudo && process.env.SUDO_USER) {
        finalCmd = 'sudo';
        finalArgs = ['-u', process.env.SUDO_USER, cmd, ...args];
        if (process.env.DISPLAY) {
            env.DISPLAY = process.env.DISPLAY;
        }
        if (process.env.XAUTHORITY) {
            env.XAUTHORITY = process.env.XAUTHORITY;
        }
    } else if (useSudo) {
        // Running as regular user, no sudo needed for GUI apps
        // (sudo would run as root which can't access user's X display)
    }

    logger.debug(`Spawning detached: ${finalCmd} ${finalArgs.join(' ')}`);
    const child = spawn(finalCmd, finalArgs, {
        detached: true,
        stdio: 'ignore',
        env: Object.keys(env).length > 0 ? env : undefined
    });
    child.on('error', (err) => {
        logger.error(`Failed to spawn ${finalCmd}: ${err.message}`);
    });
    child.on('exit', (code) => {
        if (code !== 0 && code !== null) {
            logger.warn(`${finalCmd} exited with code ${code}`);
        }
    });
    child.unref();
}

export function runInteractive(cmd: string, args: string[], useSudo: boolean = false): void {
    let finalCmd = cmd;
    let finalArgs = args;

    if (useSudo && process.env.SUDO_USER) {
        finalCmd = 'sudo';
        finalArgs = ['-E', '-u', process.env.SUDO_USER, cmd, ...args];
    } else if (useSudo) {
        finalCmd = 'sudo';
        finalArgs = [cmd, ...args];
    }

    // Ink sets terminal to raw mode; restore cooked mode before
    // handing control to an interactive child process.
    const wasRaw = process.stdin.isTTY && (process.stdin as any).isRaw;
    if (process.stdin.isTTY) {
        process.stdin.setRawMode(false);
        process.stdin.pause();
    }

    // Clear the screen and move cursor to top-left so the child
    // starts with a clean terminal area.
    process.stdout.write('\x1b[2J\x1b[0f');
    process.stdout.write(`--- Running: ${finalCmd} ${finalArgs.join(' ')} ---\n`);
    process.stdout.write('Press Ctrl+C (or appropriate quit key) to return to VMTUI\n\n');

    try {
        spawnSync(finalCmd, finalArgs, { stdio: 'inherit' });
    } finally {
        // Restore raw mode so Ink resumes correctly
        if (process.stdin.isTTY && wasRaw) {
            process.stdin.setRawMode(true);
            process.stdin.resume();
        }
        // Force a full redraw by clearing and telling Ink to repaint
        process.stdout.write('\x1b[2J\x1b[0f');
    }
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
    attachedVm?: string | null;
}

export async function getAllUsbDevices(): Promise<UsbDevice[]> {
    const devices: UsbDevice[] = [];
    const lsusb = await runCmd("lsusb", { shell: true, check: false });
    if (!lsusb) return [];

    // Get all XML files to see which USB is attached where
    // This is faster than calling virsh dumpxml for each VM
    const xmlFiles = await runCmd("sudo ls /etc/libvirt/qemu/*.xml", { shell: true, check: false });
    const vmXmls: Record<string, string> = {};
    
    if (xmlFiles) {
        const files = xmlFiles.split(/\s+/).filter(f => f.endsWith('.xml') && !f.includes('networks'));
        for (const file of files) {
            const content = await runCmd(`sudo cat ${file}`, { shell: true, check: false });
            if (content) {
                const vmName = path.basename(file, '.xml');
                vmXmls[vmName] = content;
            }
        }
    }

    const lines = lsusb.split('\n');
    for (const line of lines) {
        const match = line.match(/ID ([0-9a-fA-F]+):([0-9a-fA-F]+) (.+)/);
        if (match) {
            const vid = match[1];
            const pid = match[2];
            const name = match[3];
            let attachedVm: string | null = null;
            
            for (const [vmName, xml] of Object.entries(vmXmls)) {
                if (xml.includes(`vendor id='0x${vid}'`) && xml.includes(`product id='0x${pid}'`)) {
                    attachedVm = vmName;
                    break;
                }
            }
            
            devices.push({ 
                vid, pid, name, 
                attached: attachedVm !== null,
                attachedVm 
            });
        }
    }
    return devices;
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

export async function checkCommandExists(cmd: string): Promise<boolean> {
    const result = await runCmd(`command -v ${cmd}`, { shell: true, check: false });
    return !!result;
}

export async function tailLog(logPath: string): Promise<void> {
    if (!(await fs.access(logPath).then(() => true).catch(() => false))) {
        throw new Error(`Log file not found: ${logPath}`);
    }
    runInteractive('tail', ['-f', '-n', '50', logPath]);
}

export interface VmDisk {
    path: string;
    device: string;
    bus?: string;
    type?: string;
}

export interface VmNic {
    type: string;
    model?: string;
    mac?: string;
    source?: string;
}

export interface VmGraphics {
    type: string;
    port?: string;
    listen?: string;
}

export interface VmVideo {
    type: string;
    vram?: string;
    heads?: string;
}

export interface VmUsbDevice {
    vid: string;
    pid: string;
}

export interface VmInfo {
    name: string;
    uuid: string;
    memory: string;
    currentMemory: string;
    vcpu: number;
    cpuModel: string;
    osType: string;
    osVariant: string;
    arch: string;
    machine: string;
    disks: VmDisk[];
    nics: VmNic[];
    graphics: VmGraphics[];
    videos: VmVideo[];
    usbDevices: VmUsbDevice[];
    filesystems: { source: string; target: string }[];
    serials: string[];
    channels: string[];
}

export async function getVmInfo(vmName: string): Promise<VmInfo | null> {
    const xml = await runCmd(`virsh -c qemu:///system dumpxml ${vmName}`, { useSudo: true, check: false });
    if (!xml) return null;

    const info: VmInfo = {
        name: vmName,
        uuid: '',
        memory: '',
        currentMemory: '',
        vcpu: 0,
        cpuModel: '',
        osType: '',
        osVariant: '',
        arch: '',
        machine: '',
        disks: [],
        nics: [],
        graphics: [],
        videos: [],
        usbDevices: [],
        filesystems: [],
        serials: [],
        channels: []
    };

    const nameMatch = xml.match(/<name>([^<]+)<\/name>/);
    if (nameMatch) info.name = nameMatch[1];

    const uuidMatch = xml.match(/<uuid>([^<]+)<\/uuid>/);
    if (uuidMatch) info.uuid = uuidMatch[1];

    const memMatch = xml.match(/<memory[^>]*>(\d+)<\/memory>/);
    if (memMatch) {
        const memKiB = parseInt(memMatch[1], 10);
        info.memory = `${Math.round(memKiB / 1024)} MB`;
    }

    const curMemMatch = xml.match(/<currentMemory[^>]*>(\d+)<\/currentMemory>/);
    if (curMemMatch) {
        const memKiB = parseInt(curMemMatch[1], 10);
        info.currentMemory = `${Math.round(memKiB / 1024)} MB`;
    }

    const vcpuMatch = xml.match(/<vcpu[^>]*>(\d+)<\/vcpu>/);
    if (vcpuMatch) info.vcpu = parseInt(vcpuMatch[1], 10);

    const cpuModelMatch = xml.match(/<model[^>]*>([^<]+)<\/model>/);
    if (cpuModelMatch) info.cpuModel = cpuModelMatch[1];

    const osTypeMatch = xml.match(/<type[^>]*arch='([^']+)'[^>]*machine='([^']+)'[^>]*>([^<]+)<\/type>/);
    if (osTypeMatch) {
        info.arch = osTypeMatch[1];
        info.machine = osTypeMatch[2];
        info.osType = osTypeMatch[3];
    }

    const osVariantMatch = xml.match(/<os[^>]*>[\s\S]*?<\/os>/);
    if (osVariantMatch) {
        const variant = osVariantMatch[0].match(/<osinfo [^>]*id='([^']+)'/);
        if (variant) info.osVariant = variant[1];
    }

    const diskMatches = xml.matchAll(/<disk[^>]*type='([^']+)'[^>]*device='([^']+)'[^>]*>[\s\S]*?<\/disk>/g);
    for (const m of diskMatches) {
        const diskXml = m[0];
        const sourceMatch = diskXml.match(/<source[^>]*(?:file|dev|pool|volume)='([^']+)'/);
        const busMatch = diskXml.match(/<target[^>]*bus='([^']+)'/);
        if (sourceMatch) {
            info.disks.push({
                path: sourceMatch[1],
                device: m[2],
                bus: busMatch ? busMatch[1] : undefined,
                type: m[1]
            });
        }
    }

    const nicMatches = xml.matchAll(/<interface[^>]*type='([^']+)'[^>]*>[\s\S]*?<\/interface>/g);
    for (const m of nicMatches) {
        const nicXml = m[0];
        const modelMatch = nicXml.match(/<model[^>]*type='([^']+)'/);
        const macMatch = nicXml.match(/<mac[^>]*address='([^']+)'/);
        const sourceMatch = nicXml.match(/<source[^>]*(?:network|bridge|dev)='([^']+)'/);
        info.nics.push({
            type: m[1],
            model: modelMatch ? modelMatch[1] : undefined,
            mac: macMatch ? macMatch[1] : undefined,
            source: sourceMatch ? sourceMatch[1] : undefined
        });
    }

    const graphicsMatches = xml.matchAll(/<graphics[^>]*type='([^']+)'[^>]*\/?>/g);
    for (const m of graphicsMatches) {
        const gfxXml = m[0];
        const portMatch = gfxXml.match(/port='(\d+)'/);
        const listenMatch = gfxXml.match(/listen='([^']+)'/);
        info.graphics.push({
            type: m[1],
            port: portMatch ? portMatch[1] : undefined,
            listen: listenMatch ? listenMatch[1] : undefined
        });
    }

    const videoMatches = xml.matchAll(/<video>[\s\S]*?<\/video>/g);
    for (const m of videoMatches) {
        const videoXml = m[0];
        const modelMatch = videoXml.match(/<model[^>]*type='([^']+)'/);
        const vramMatch = videoXml.match(/vram='(\d+)'/);
        const headsMatch = videoXml.match(/heads='(\d+)'/);
        if (modelMatch) {
            info.videos.push({
                type: modelMatch[1],
                vram: vramMatch ? vramMatch[1] : undefined,
                heads: headsMatch ? headsMatch[1] : undefined
            });
        }
    }

    const usbMatches = xml.matchAll(/<hostdev[^>]*type='usb'[^>]*>[\s\S]*?<\/hostdev>/g);
    for (const m of usbMatches) {
        const usbXml = m[0];
        const vidMatch = usbXml.match(/vendor[^>]*id='0x([^']+)'/);
        const pidMatch = usbXml.match(/product[^>]*id='0x([^']+)'/);
        if (vidMatch && pidMatch) {
            info.usbDevices.push({ vid: vidMatch[1], pid: pidMatch[1] });
        }
    }

    const fsMatches = xml.matchAll(/<filesystem[^>]*>[\s\S]*?<\/filesystem>/g);
    for (const m of fsMatches) {
        const fsXml = m[0];
        const sourceMatch = fsXml.match(/<source[^>]*dir='([^']+)'/);
        const targetMatch = fsXml.match(/<target[^>]*dir='([^']+)'/);
        if (sourceMatch && targetMatch) {
            info.filesystems.push({ source: sourceMatch[1], target: targetMatch[1] });
        }
    }

    const serialMatches = xml.matchAll(/<serial[^>]*type='([^']+)'[^>]*\/?>/g);
    for (const m of serialMatches) {
        info.serials.push(m[1]);
    }

    const channelMatches = xml.matchAll(/<channel[^>]*type='([^']+)'[^>]*\/?>/g);
    for (const m of channelMatches) {
        info.channels.push(m[1]);
    }

    return info;
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
