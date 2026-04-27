import * as winston from 'winston';
export declare const logger: winston.Logger;
export declare function runCmd(cmd: string | string[], options?: {
    shell?: boolean;
    check?: boolean;
}): Promise<string | null>;
export interface VmState {
    name: string;
    state: string;
}
export declare function getVmStates(): Promise<Record<string, string>>;
export declare function checkSystemHealth(): Promise<boolean>;
//# sourceMappingURL=system.d.ts.map