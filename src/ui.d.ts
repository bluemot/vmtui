import * as blessed from 'blessed';
export declare class UIManager {
    private screen;
    private header;
    private footer;
    private currentVM;
    private cachedState;
    constructor();
    updateStatus(vmName: string, state: string): void;
    private updateHeader;
    showMenu(title: string, items: string[]): Promise<number>;
    msgBox(message: string, title?: string): Promise<void>;
    inputBox(prompt: string, defaultValue?: string): Promise<string>;
    getScreen(): blessed.Widgets.Screen;
}
//# sourceMappingURL=ui.d.ts.map