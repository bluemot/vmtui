export interface VMEntry {
    dir: string;
    host_share: string;
    installing?: boolean;
}
export interface Config {
    host_share_dir: string;
}
export declare const SUDO_USER: string | undefined;
export declare const USER_HOME: string;
export declare let HOST_SHARE_DIR: string;
export declare const DEFAULT_LINUX_DIR: string;
export declare const DEFAULT_WINDOWS_DIR: string;
export declare const COMMON_ISO_DIR: string;
export declare let VM_REGISTRY: Record<string, VMEntry>;
export declare function loadConfig(): Promise<void>;
export declare function saveConfig(): Promise<void>;
export declare function saveRegistry(): Promise<void>;
export declare function setHostShareDir(newPath: string): void;
//# sourceMappingURL=config.d.ts.map