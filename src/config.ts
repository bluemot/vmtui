import * as fs from 'fs/promises';
import * as path from 'path';
import * as os from 'os';

export interface VMEntry {
    dir: string;
    host_share: string;
    installing?: boolean;
}

export interface Config {
    host_share_dir: string;
}

const CONFIG_FILE = "vmtui.json";
const VM_REGISTRY_FILE = "vms.json";

export const SUDO_USER = process.env.SUDO_USER;
export const USER_HOME = SUDO_USER ? path.join('/home', SUDO_USER) : os.homedir();

export let HOST_SHARE_DIR = path.join(USER_HOME, "driver_projects");
export const DEFAULT_LINUX_DIR = path.resolve("vms");
export const DEFAULT_WINDOWS_DIR = path.resolve("win_vms");
export const COMMON_ISO_DIR = path.join(USER_HOME, "Downloads");

export let VM_REGISTRY: Record<string, VMEntry> = {};

export async function loadConfig() {
    try {
        const data = await fs.readFile(CONFIG_FILE, 'utf-8');
        const conf: Config = JSON.parse(data);
        HOST_SHARE_DIR = conf.host_share_dir || HOST_SHARE_DIR;
    } catch (e) {
        // Ignore missing config
    }

    try {
        const data = await fs.readFile(VM_REGISTRY_FILE, 'utf-8');
        const rawRegistry = JSON.parse(data);
        
        // Migration: Convert old string entries to dict
        let migrated = false;
        for (const [k, v] of Object.entries(rawRegistry)) {
            if (typeof v === 'string') {
                VM_REGISTRY[k] = { dir: v, host_share: HOST_SHARE_DIR };
                migrated = true;
            } else {
                VM_REGISTRY[k] = v as VMEntry;
            }
        }
        if (migrated) await saveRegistry();
    } catch (e) {
        VM_REGISTRY = {};
    }

    if (Object.keys(VM_REGISTRY).length === 0) {
        await scanAndRegister(DEFAULT_LINUX_DIR);
        await scanAndRegister(DEFAULT_WINDOWS_DIR);
    }
}

export async function saveConfig() {
    try {
        await fs.writeFile(CONFIG_FILE, JSON.stringify({ host_share_dir: HOST_SHARE_DIR }, null, 4));
    } catch (e) {
        console.error("Failed to save config:", e);
    }
}

export async function saveRegistry() {
    try {
        await fs.writeFile(VM_REGISTRY_FILE, JSON.stringify(VM_REGISTRY, null, 4));
    } catch (e) {
        console.error("Failed to save registry:", e);
    }
}

async function scanAndRegister(baseDir: string) {
    try {
        const dirs = await fs.readdir(baseDir, { withFileTypes: true });
        for (const dirent of dirs) {
            if (dirent.isDirectory()) {
                const p = path.join(baseDir, dirent.name);
                if (!VM_REGISTRY[dirent.name]) {
                    try {
                        await fs.access(path.join(p, `${dirent.name}.qcow2`));
                        VM_REGISTRY[dirent.name] = { dir: p, host_share: HOST_SHARE_DIR };
                    } catch (e) {
                        // Skip if qcow2 doesn't exist
                    }
                }
            }
        }
        await saveRegistry();
    } catch (e) {
        // Directory might not exist
    }
}

export const LINUX_IMAGES: Record<string, any> = {
    "Ubuntu 24.04 (Noble) Server": {
        "url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        "file": "noble-server-cloudimg-amd64.img",
        "variant": "ubuntu24.04",
        "desktop": false
    },
    "Ubuntu 24.04 (Noble) Desktop": {
        "url": "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img",
        "file": "noble-server-cloudimg-amd64.img",
        "variant": "ubuntu24.04",
        "desktop": true
    },
    "Ubuntu 22.04 (Jammy) Server": {
        "url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "file": "jammy-server-cloudimg-amd64.img",
        "variant": "ubuntu22.04",
        "desktop": false
    },
    "Ubuntu 22.04 (Jammy) Desktop": {
        "url": "https://cloud-images.ubuntu.com/jammy/current/jammy-server-cloudimg-amd64.img",
        "file": "jammy-server-cloudimg-amd64.img",
        "variant": "ubuntu22.04",
        "desktop": true
    },
    "Debian 12 (Bookworm) Server": {
        "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2",
        "file": "debian-12-generic-amd64.qcow2",
        "variant": "debian12",
        "desktop": false
    },
    "Debian 12 (Bookworm) Desktop": {
        "url": "https://cloud.debian.org/images/cloud/bookworm/latest/debian-12-generic-amd64.qcow2",
        "file": "debian-12-generic-amd64.qcow2",
        "variant": "debian12",
        "desktop": true
    }
};

export const VIRTIO_URL = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/latest-virtio/virtio-win.iso";

export function setHostShareDir(newPath: string) {
    HOST_SHARE_DIR = newPath;
}
