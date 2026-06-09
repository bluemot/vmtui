import React, { useState, useEffect } from 'react';
import { Text, Box, useApp, useInput } from 'ink';
import SelectInput from 'ink-select-input';
import TextInput from 'ink-text-input';
import * as fs from 'fs/promises';
import * as path from 'path';
import * as config from './config.js';
import * as system from './system.js';
import { FileBrowser } from './FileBrowser.js';

const PasswordPrompt = ({ onSubmit, error }: { onSubmit: (pass: string) => void, error?: string }) => {
    const [value, setValue] = useState('');
    return (
        <Box flexDirection="column" alignItems="center" marginTop={2}>
            <Text bold color="blue">🔐 Sudo Authentication Required</Text>
            <Box marginTop={1}>
                <Text>This tool requires root privileges for VM management.</Text>
            </Box>
            {error && (
                <Box marginTop={1} paddingX={1} borderStyle="single" borderColor="red">
                    <Text color="red">{error}</Text>
                </Box>
            )}
            <Box marginTop={1} flexDirection="column" width={40}>
                <Text>Enter sudo password:</Text>
                <Box borderStyle="single" borderColor="green" paddingX={1}>
                    <TextInput value={value} onChange={setValue} onSubmit={() => onSubmit(value)} mask="*" />
                </Box>
            </Box>
            <Box marginTop={1}>
                <Text dimColor>Press Enter to submit, Ctrl+C to quit</Text>
            </Box>
        </Box>
    );
};

const MainMenu = ({ onSelect, activeVm }: { onSelect: (value: string) => void, activeVm: string }) => {
    const [focusArea, setFocusArea] = useState<'categories' | 'items'>('categories');
    const [activeCategory, setActiveCategory] = useState('manage');
    const [usbDevices, setUsbDevices] = useState<system.UsbDevice[]>([]);

    const categories = [
        { label: ' 🛠  VM Manage    ', value: 'manage' },
        { label: ' ⚡  Power/Pause  ', value: 'power' },
        { label: ' 👁  View/Logs    ', value: 'view' },
        { label: ' 🔌  USB Manager  ', value: 'usb' },
        { label: ' 🔄  Switch VM   ', value: 'switch' },
        { label: ' 🚪  Quit        ', value: 'quit' }
    ];

    const vmItems = Object.keys(config.VM_REGISTRY).map(name => ({
        label: name === activeVm ? `● ${name} (Active)` : `○ ${name}`,
        value: `select-vm:${name}`
    }));

    useEffect(() => {
        if (activeCategory === 'usb') {
            system.getAllUsbDevices().then(setUsbDevices);
        }
    }, [activeCategory]);

    const usbItems = usbDevices.map(d => {
        let label = d.attached ? `[ON] ` : `[  ] `;
        label += `${d.vid}:${d.pid} ${d.name}`;
        if (d.attached && d.attachedVm) {
            label += ` (${d.attachedVm.substring(0, 5)})`;
        }
        return { label, value: `usb-toggle:${d.vid}:${d.pid}` };
    });

    const subItems: Record<string, { label: string, value: string }[]> = {
        manage: [
            { label: '1. Setup Host Environment', value: 'setup' },
            { label: '2. Create New VM', value: 'create' },
            { label: '3. Duplicate Active VM', value: 'duplicate' },
            { label: '4. Import / Rescue VM', value: 'import' },
            { label: '5. Resize VM Disk', value: 'resize' },
            { label: '6. VM Individual Settings', value: 'settings' },
            { label: '7. Delete Active VM', value: 'delete' },
            { label: '8. VM Info (Hardware/OS)', value: 'vm-info' },
        ],
        power: [
            { label: '1. Start / Restore', value: 'start' },
            { label: '2. Force Stop VM', value: 'stop' },
            { label: '3. Hibernate (ManagedSave)', value: 'hibernate' },
            { label: '4. Guest Suspend (RAM/S3)', value: 'suspend' },
            { label: '5. Guest Hibernate (Disk/S4)', value: 'ghibernate' },
            { label: '6. Host Pause (Freeze)', value: 'pause' },
            { label: '7. Resume / Wakeup', value: 'resume' },
        ],
        view: [
            { label: '1. Console (Text Access)', value: 'console' },
            { label: '2. Tail Install/Boot Log', value: 'tail' },
            { label: '3. Viewer (Graphical)', value: 'viewer' },
        ],
        usb: usbItems.length > 0 ? usbItems : [{ label: 'No USB devices found', value: 'noop' }],
        switch: vmItems.length > 0 ? vmItems : [{ label: 'No VMs found', value: 'noop' }],
        quit: [
            { label: 'Confirm Exit', value: 'quit' }
        ]
    };

    const handleCategoryHighlight = (item: any) => {
        setActiveCategory(item.value);
    };

    const handleCategorySelect = (item: any) => {
        if (item.value === 'quit') {
            onSelect('quit');
        } else {
            setFocusArea('items');
        }
    };

    useInput((input, key) => {
        if (focusArea === 'categories' && key.rightArrow) {
            if (activeCategory !== 'quit') {
                setFocusArea('items');
            }
        }
        if (focusArea === 'items' && (key.leftArrow || key.escape || key.backspace)) {
            setFocusArea('categories');
        }
        if (activeCategory === 'usb' && focusArea === 'items' && (input === 'a' || input === 'A')) {
            // Trigger select manually for 'a' key
            // This is a bit tricky with ink-select-input, but we can't easily get the current highlighted item here
            // SelectInput handles its own state.
        }
    });

    return (
        <Box flexDirection="column">
            <Text bold color="blue">Main Menu</Text>
            <Box flexDirection="row" marginTop={1}>
                {/* Left Column: Categories */}
                <Box flexDirection="column" borderStyle="round" borderColor={focusArea === 'categories' ? 'blue' : 'gray'} paddingX={1} width={25}>
                    <SelectInput 
                        items={categories} 
                        onSelect={handleCategorySelect}
                        onHighlight={handleCategoryHighlight}
                        isFocused={focusArea === 'categories'}
                    />
                </Box>

                {/* Right Column: Sub-items */}
                <Box 
                    flexDirection="column" 
                    borderStyle="round" 
                    borderColor={focusArea === 'items' ? 'green' : 'gray'} 
                    paddingX={1} 
                    marginLeft={1}
                    flexGrow={1}
                >
                    <Box marginBottom={1}>
                        <Text italic color="cyan">
                            {categories.find(c => c.value === activeCategory)?.label.trim()} options:
                        </Text>
                    </Box>
                    <SelectInput 
                        items={subItems[activeCategory] || []} 
                        onSelect={(item) => {
                            if (item.value === 'back') setFocusArea('categories');
                            else {
                                onSelect(item.value);
                                if (activeCategory === 'usb') {
                                    // Refresh USB list after action
                                    setTimeout(() => system.getAllUsbDevices().then(setUsbDevices), 1000);
                                }
                            }
                        }}
                        isFocused={focusArea === 'items'}
                    />
                    {focusArea === 'items' && (
                        <Box marginTop={1}>
                            <Text dimColor>← Left / Esc to back</Text>
                            {activeCategory === 'usb' && <Text color="yellow"> | Enter/A to toggle</Text>}
                        </Box>
                    )}
                    {focusArea === 'categories' && activeCategory !== 'quit' && (
                        <Box marginTop={1}>
                            <Text dimColor>→ Right to open</Text>
                        </Box>
                    )}
                </Box>
            </Box>
        </Box>
    );
};

const SetupMenu = ({ onSelect }: { onSelect: (item: any) => void }) => {
    const items = [
        { label: '1. Install/Update KVM Packages', value: 'install' },
        { label: '2. Change Host Share Directory', value: 'share' },
        { label: 'Back', value: 'back' }
    ];

    return (
        <Box flexDirection="column">
            <Text bold color="blue">Host Setup Environment</Text>
            <SelectInput items={items} onSelect={onSelect} />
        </Box>
    );
};

const CreateVMWizard = ({ onComplete, onCancel }: { onComplete: (data: any) => void, onCancel: () => void }) => {
    const [step, setStep] = useState(0);
    const [name, setName] = useState('my-vm');
    const [osType, setOsType] = useState<'win' | 'linux-cloud' | 'linux-iso'>('linux-cloud');
    const [distro, setDistro] = useState(Object.keys(config.LINUX_IMAGES)[0]);
    const [diskSize, setDiskSize] = useState('64G');

    const handleNext = () => setStep(s => s + 1);

    return (
        <Box flexDirection="column">
            <Text bold color="blue">Create New VM Wizard (Step {step + 1})</Text>
            
            {step === 0 && (
                <Box flexDirection="column">
                    <Text>Enter VM Name:</Text>
                    <Box borderStyle="single" borderColor="green" paddingX={1}>
                        <TextInput value={name} onChange={setName} onSubmit={handleNext} />
                    </Box>
                </Box>
            )}

            {step === 1 && (
                <Box flexDirection="column">
                    <Text>Select Operating System:</Text>
                    <SelectInput 
                        items={[
                            { label: 'Linux Cloud Image (Auto-Install)', value: 'linux-cloud' },
                            { label: 'Windows 10 / 11 (ISO Install)', value: 'win' },
                            { label: 'Linux (ISO Install - Manual)', value: 'linux-iso' }
                        ]} 
                        onSelect={(item) => { 
                            setOsType(item.value as any); 
                            if (item.value === 'linux-cloud') setStep(2);
                            else setStep(3); // Skip distro selection for ISOs for now
                        }} 
                    />
                </Box>
            )}

            {step === 2 && (
                <Box flexDirection="column">
                    <Text>Select Linux Distribution:</Text>
                    <SelectInput 
                        items={Object.keys(config.LINUX_IMAGES).map(k => ({ label: k, value: k }))} 
                        onSelect={(item) => { setDistro(item.value); handleNext(); }} 
                    />
                </Box>
            )}

            {step === 3 && (
                <Box flexDirection="column">
                    <Text>Enter Disk Size (e.g. 64G, 128G):</Text>
                    <Box borderStyle="single" borderColor="green" paddingX={1}>
                        <TextInput value={diskSize} onChange={setDiskSize} onSubmit={() => onComplete({ name, osType, distro, diskSize })} />
                    </Box>
                </Box>
            )}

            <Box marginTop={1}>
                <Text dimColor>Press Esc to Cancel (Not yet hooked up)</Text>
                <Text color="yellow"> [ Back to Main ] </Text>
            </Box>
        </Box>
    );
};

const VMInfoPanel = ({ vmName, info, onBack }: { vmName: string, info: system.VmInfo | null, onBack: () => void }) => {
    useInput((input, key) => {
        if (key.escape || key.backspace || input === 'q' || input === 'Q') {
            onBack();
        }
    });

    if (!info) {
        return (
            <Box flexDirection="column" padding={1}>
                <Text bold color="red">Failed to retrieve VM info for {vmName}</Text>
                <Box marginTop={1}>
                    <Text dimColor>Press Q / Esc to go back</Text>
                </Box>
            </Box>
        );
    }

    const SectionHeader = ({ icon, title }: { icon: string, title: string }) => (
        <Box marginTop={1}>
            <Text bold color="yellow">{icon} {title}</Text>
        </Box>
    );

    return (
        <Box flexDirection="column" padding={1}>
            <Text bold color="blue">📋 VM Info: {info.name}</Text>
            <Box borderStyle="round" borderColor="cyan" paddingX={1} marginTop={1} flexDirection="column">
                <Text bold color="yellow">🖥  Basic</Text>
                <Text>  Name:     {info.name}</Text>
                <Text>  UUID:     {info.uuid}</Text>
                <Text>  Memory:   {info.memory} (current: {info.currentMemory})</Text>
                <Text>  vCPUs:    {info.vcpu}</Text>
                {info.cpuModel && <Text>  CPU:      {info.cpuModel}</Text>}
                <Text>  OS Type:  {info.osType}</Text>
                {info.osVariant && <Text>  OS Var:   {info.osVariant}</Text>}
                <Text>  Arch:     {info.arch}</Text>
                <Text>  Machine:  {info.machine}</Text>

                {info.disks.length > 0 && (
                    <>
                        <SectionHeader icon="💾" title="Disks" />
                        {info.disks.map((d, i) => (
                            <Text key={i}>  [{d.device}] {d.path} {d.bus ? `(bus: ${d.bus})` : ''}</Text>
                        ))}
                    </>
                )}

                {info.nics.length > 0 && (
                    <>
                        <SectionHeader icon="🌐" title="Network" />
                        {info.nics.map((n, i) => (
                            <Text key={i}>  {n.type} {n.model ? `(${n.model})` : ''} {n.mac} {n.source ? `→ ${n.source}` : ''}</Text>
                        ))}
                    </>
                )}

                {info.graphics.length > 0 && (
                    <>
                        <SectionHeader icon="🖼" title="Graphics" />
                        {info.graphics.map((g, i) => (
                            <Text key={i}>  {g.type} {g.port ? `port: ${g.port}` : ''} {g.listen ? `listen: ${g.listen}` : ''}</Text>
                        ))}
                    </>
                )}

                {info.videos.length > 0 && (
                    <>
                        <SectionHeader icon="🎬" title="Video" />
                        {info.videos.map((v, i) => (
                            <Text key={i}>  {v.type} {v.vram ? `vram: ${v.vram}KB` : ''} {v.heads ? `heads: ${v.heads}` : ''}</Text>
                        ))}
                    </>
                )}

                {info.usbDevices.length > 0 && (
                    <>
                        <SectionHeader icon="🔌" title="USB" />
                        {info.usbDevices.map((u, i) => (
                            <Text key={i}>  VID: {u.vid} PID: {u.pid}</Text>
                        ))}
                    </>
                )}

                {info.filesystems.length > 0 && (
                    <>
                        <SectionHeader icon="📁" title="Filesystems" />
                        {info.filesystems.map((f, i) => (
                            <Text key={i}>  {f.source} → {f.target}</Text>
                        ))}
                    </>
                )}

                {info.serials.length > 0 && (
                    <>
                        <SectionHeader icon="🔌" title="Serials" />
                        {info.serials.map((s, i) => (
                            <Text key={i}>  type: {s}</Text>
                        ))}
                    </>
                )}

                {info.channels.length > 0 && (
                    <>
                        <SectionHeader icon="📡" title="Channels" />
                        {info.channels.map((c, i) => (
                            <Text key={i}>  type: {c}</Text>
                        ))}
                    </>
                )}
            </Box>
            <Box marginTop={1}>
                <Text dimColor>Press Q / Esc to go back</Text>
            </Box>
        </Box>
    );
};

export const App = () => {
    const { exit } = useApp();
    const [activeVm, setActiveVm] = useState<string>('');
    const [vmState, setVmState] = useState<string>('Stopped');
    const [view, setView] = useState<'main' | 'setup' | 'browser' | 'create' | 'auth' | 'vm-info'>('auth');
    const [message, setMessage] = useState<string>('');
    const [passwordError, setPasswordError] = useState<string>('');
    const [vmInfoData, setVmInfoData] = useState<system.VmInfo | null>(null);
    const [browserMode, setBrowserMode] = useState<'file' | 'directory'>('directory');
    const [browserTitle, setBrowserTitle] = useState<string>('Select Directory');
    const [browserStartPath, setBrowserStartPath] = useState<string>(config.USER_HOME);
    const [onBrowserSelect, setOnBrowserSelect] = useState<(path: string | null) => void>(() => {});

    const refreshData = async () => {
        config.loadConfig();
        const states = await system.getVmStates();
        if (activeVm) {
            setVmState(states[activeVm] || 'Stopped');
        }
        setMessage('Data refreshed.');
    };

    useInput((input, key) => {
        if (view === 'auth') {
            if (key.ctrl && input === 'c') {
                exit();
            }
            return;
        }
        if (input === 'q' || input === 'Q') {
            if (view === 'main') exit();
        }
        if (input === 'r' || input === 'R') {
            refreshData();
        }
    });

    useEffect(() => {
        const checkAuth = async () => {
            if (system.isRoot()) {
                setView('main');
                return;
            }
            const noPass = await system.checkSudoNoPassword();
            if (noPass) {
                setView('main');
            }
        };
        checkAuth();
    }, []);

    useEffect(() => {
        if (view !== 'main') return;
        refreshData();
        const timer = setInterval(async () => {
            const states = await system.getVmStates();
            if (activeVm) {
                setVmState(states[activeVm] || 'Stopped');
            }
        }, 5000);

        return () => clearInterval(timer);
    }, [activeVm, view]);

    const handleSelect = async (value: string) => {
        if (value === 'quit') {
            exit();
            return;
        }

        setMessage(''); // Clear previous message

        if (value.startsWith('select-vm:')) {
            const vmName = value.split(':')[1];
            if (vmName) {
                setActiveVm(vmName);
                setMessage(`Selected VM: ${vmName}`);
            }
            return;
        }

        if (value.startsWith('usb-toggle:')) {
            if (!activeVm) {
                setMessage('No active VM selected to attach/detach USB.');
                return;
            }
            const [_, vid, pid] = value.split(':');
            const devices = await system.getAllUsbDevices();
            const dev = devices.find(d => d.vid === vid && d.pid === pid);
            if (dev) {
                const targetVm = dev.attached ? (dev.attachedVm || activeVm) : activeVm;
                setMessage(`${dev.attached ? 'Detaching' : 'Attaching'} USB ${vid}:${pid} ${dev.attached ? 'from' : 'to'} ${targetVm}...`);
                await system.toggleUsbDevice(targetVm, dev);
                setMessage(`USB ${vid}:${pid} ${dev.attached ? 'detached' : 'attached'}.`);
            }
            return;
        }

        if (value === 'switch') {
            return;
        }

        if (value === 'setup') {
            setView('setup');
            return;
        }

        if (value === 'create') {
            setView('create');
            return;
        }

        if (!activeVm && !['setup', 'create', 'import', 'switch'].includes(value)) {
            setMessage('No active VM selected.');
            return;
        }

        try {
            switch (value) {
                case 'start':
                    setMessage(`Starting ${activeVm}...`);
                    try {
                        await system.runCmd(`virsh -c qemu:///system start ${activeVm}`, { useSudo: true, check: true });
                        setMessage(`Start command sent to ${activeVm}`);
                        system.spawnDetached('virt-viewer', ['--connect', 'qemu:///system', '--attach', activeVm], true);
                    } catch (e: any) {
                        const err = e.message || "";
                        if (err.includes("apparmor") || err.includes("unsupported configuration") || err.includes("qxl") || err.includes("spice") || err.includes("virtiofsd")) {
                            setMessage(`Attempting auto-fix for ${activeVm}...`);
                            const xml = await system.runCmd(`virsh -c qemu:///system dumpxml ${activeVm}`, { useSudo: true });
                            if (xml) {
                                let fixedXml = xml;
                                // 1. Fix Video: QXL -> VGA and remove 'ram'
                                fixedXml = fixedXml.replace(/<model type='qxl'[^>]*\/>/g, "<model type='vga' vram='16384' heads='1' primary='yes'/>");
                                
                                // 2. Fix Graphics: Spice -> VNC
                                fixedXml = fixedXml.replace(/type='spice'/g, "type='vnc'");
                                fixedXml = fixedXml.replace(/<image compression='off'\/>/g, "");
                                fixedXml = fixedXml.replace(/<audio id='1' type='spice'[^>]*\/>/g, "");
                                
                                // 3. Fix Channels/Redirdev: Remove SPICE dependent parts
                                fixedXml = fixedXml.replace(/<channel type='spicevmc'>[\s\S]*?<\/channel>/g, "");
                                fixedXml = fixedXml.replace(/<redirdev[\s\S]*?<\/redirdev>/g, "");
                                
                                // 4. Fix AppArmor
                                fixedXml = fixedXml.replace(/<seclabel type='dynamic' model='apparmor'[^>]*>[\s\S]*?<\/seclabel>/g, "");
                                
                                const tmpPath = `/tmp/vmtui_fix_${activeVm}.xml`;
                                await fs.writeFile(tmpPath, fixedXml);
                                await system.defineVm(tmpPath);
                                
                                // Try starting again
                                try {
                                    await system.runCmd(`virsh -c qemu:///system start ${activeVm}`, { useSudo: true, check: true });
                                    setMessage(`VM ${activeVm} fixed and started.`);
                                    system.spawnDetached('virt-viewer', ['--connect', 'qemu:///system', '--attach', activeVm], true);
                                } catch (e2: any) {
                                    setMessage(`Auto-fix failed to start VM: ${e2.message}`);
                                }
                            }
                        } else {
                            throw e;
                        }
                    }
                    break;
                case 'stop':
                    setMessage(`Force stopping ${activeVm}...`);
                    await system.runCmd(`virsh -c qemu:///system destroy ${activeVm}`, { useSudo: true });
                    setMessage(`Force stop command sent to ${activeVm}`);
                    break;
                case 'pause':
                    setMessage(`Pausing ${activeVm}...`);
                    await system.runCmd(`virsh -c qemu:///system suspend ${activeVm}`, { useSudo: true });
                    setMessage(`Pause command sent to ${activeVm}`);
                    break;
                case 'import':
                    setBrowserMode('directory');
                    setBrowserTitle('Select VM Directory to Import');
                    setBrowserStartPath(process.cwd());
                    setOnBrowserSelect(() => async (dir: string | null) => {
                        if (dir) {
                            const name = path.basename(dir);
                            setMessage(`Importing ${name} from ${dir}...`);
                            config.VM_REGISTRY[name] = { dir, host_share: config.HOST_SHARE_DIR };
                            await config.saveRegistry();
                            setActiveVm(name);
                            setMessage(`VM ${name} imported to registry.`);
                        }
                        setView('main');
                    });
                    setView('browser');
                    break;
                case 'resume':
                    setMessage(`Resuming/Waking ${activeVm}...`);
                    await system.runCmd(`virsh -c qemu:///system resume ${activeVm}`, { useSudo: true });
                    setMessage(`Resume command sent to ${activeVm}`);
                    break;
                case 'resize':
                    setMessage(`Resize feature for ${activeVm} not yet implemented.`);
                    break;
                case 'hibernate':
                    setMessage(`Hibernating (ManagedSave) ${activeVm}...`);
                    await system.runCmd(`virsh -c qemu:///system managedsave ${activeVm}`, { useSudo: true });
                    setMessage(`Hibernate command sent to ${activeVm}`);
                    break;
                case 'console':
                    setMessage(`Entering console for ${activeVm}... (UI will pause)`);
                    setTimeout(() => {
                        system.runInteractive('virsh', ['-c', 'qemu:///system', 'console', activeVm], true);
                        setMessage(`Exited console for ${activeVm}`);
                    }, 500);
                    break;
                case 'tail':
                    const vmInfo = config.VM_REGISTRY[activeVm];
                    if (vmInfo && vmInfo.dir) {
                        const logPath = path.join(vmInfo.dir, `${activeVm}-console.log`);
                        setMessage(`Tailing log for ${activeVm}... (UI will pause)`);
                        setTimeout(async () => {
                            try {
                                await system.tailLog(logPath);
                                setMessage(`Exited log tail for ${activeVm}`);
                            } catch (e: any) {
                                setMessage(`Error: ${e.message}`);
                            }
                        }, 500);
                    } else {
                        setMessage(`VM directory not found for ${activeVm}`);
                    }
                    break;
                case 'viewer': {
                    setMessage(`Checking for virt-viewer...`);
                    const hasViewer = await system.checkCommandExists('virt-viewer');
                    if (!hasViewer) {
                        setMessage('Error: virt-viewer not found. Install it with: sudo apt install virt-viewer');
                        break;
                    }
                    setMessage(`Launching viewer for ${activeVm}...`);
                    system.spawnDetached('virt-viewer', ['--connect', 'qemu:///system', '--attach', activeVm], true);
                    setMessage(`Viewer launched for ${activeVm}`);
                    break;
                }
                case 'vm-info': {
                    setMessage(`Fetching info for ${activeVm}...`);
                    const info = await system.getVmInfo(activeVm);
                    if (info) {
                        setVmInfoData(info);
                        setView('vm-info');
                        setMessage('');
                    } else {
                        setMessage(`Failed to get info for ${activeVm}`);
                    }
                    break;
                }
                default:
                    setMessage(`Feature ${value} not fully implemented yet.`);
            }
        } catch (e: any) {
            setMessage(`Error: ${e.message}`);
        }
    };

    const handleSetupSelect = async (item: any) => {
        if (item.value === 'back') {
            setView('main');
            return;
        }

        if (item.value === 'install') {
            setMessage('Installing KVM packages... (Check vmtui.log for details)');
            try {
                const pkgs = [
                    "qemu-system-x86", "libvirt-daemon-system", "libvirt-clients", "virtinst", 
                    "virt-viewer", "swtpm", "swtpm-tools", "acl", "ovmf", 
                    "cloud-image-utils", "unzip", "wireless-tools", "bridge-utils",
                    "libnss-libvirt", "virtiofsd"
                ];
                await system.runCmd(`apt update`, { useSudo: true });
                await system.runCmd(`apt install -y ${pkgs.join(' ')}`, { useSudo: true });
                await system.checkSystemHealth();
                setMessage('KVM Packages installed and system health checked.');
            } catch (e: any) {
                setMessage(`Installation failed: ${e.message}`);
            }
        } else if (item.value === 'share') {
            setBrowserMode('directory');
            setBrowserTitle('Select Host Share Directory');
            setBrowserStartPath(config.HOST_SHARE_DIR);
            setOnBrowserSelect(() => (path: string | null) => {
                if (path) {
                    config.setHostShareDir(path);
                    config.saveConfig();
                    setMessage(`Host share directory updated to: ${path}`);
                }
                setView('setup');
            });
            setView('browser');
        }
    };

    const handleCreateComplete = async (data: any) => {
        setView('main');
        setMessage(`Creating VM ${data.name}... (Check vmtui.log)`);
        
        try {
            const vmDir = path.join(config.DEFAULT_LINUX_DIR, data.name);
            await fs.mkdir(vmDir, { recursive: true });
            if (config.SUDO_USER) {
                await system.runCmd(`chown ${config.SUDO_USER}:${config.SUDO_USER} ${vmDir}`, { useSudo: true });
            }

            if (data.osType === 'linux-cloud') {
                const imgData = config.LINUX_IMAGES[data.distro];
                const diskPath = path.join(vmDir, `${data.name}.qcow2`);
                await system.createLinuxCloudVM(data.name, vmDir, diskPath, data.diskSize, imgData, config.HOST_SHARE_DIR);
                config.VM_REGISTRY[data.name] = { dir: vmDir, host_share: config.HOST_SHARE_DIR, installing: true };
                await config.saveRegistry();
                setActiveVm(data.name);
                setMessage(`VM ${data.name} created successfully.`);
            } else {
                setMessage(`Creation for ${data.osType} not yet fully implemented in TS.`);
            }
        } catch (e: any) {
            setMessage(`Failed to create VM: ${e.message}`);
        }
    };

    return (
        <Box flexDirection="column" padding={1}>
            {view !== 'auth' && (
                <Box borderStyle="round" borderColor="blue" paddingX={1} marginBottom={1}>
                    <Text bold> VMTUI (Ink) </Text>
                    <Box marginLeft={2}>
                        <Text>Active VM: </Text>
                        <Text color="green">{activeVm || 'None'}</Text>
                    </Box>
                    <Box marginLeft={2}>
                        <Text>Status: </Text>
                        <Text color="yellow">[{vmState}]</Text>
                    </Box>
                </Box>
            )}

            {view === 'auth' && (
                <PasswordPrompt
                    onSubmit={(pass) => {
                        system.initSudoAuth(pass).then((valid) => {
                            if (valid) {
                                setPasswordError('');
                                setView('main');
                            } else {
                                setPasswordError('Incorrect password. Please try again.');
                            }
                        });
                    }}
                    error={passwordError}
                />
            )}

            {view === 'main' && <MainMenu key="main" onSelect={handleSelect} activeVm={activeVm} />}

            {view === 'setup' && <SetupMenu key="setup" onSelect={handleSetupSelect} />}

            {view === 'create' && <CreateVMWizard onComplete={handleCreateComplete} onCancel={() => setView('main')} />}

            {view === 'browser' && (
                <FileBrowser
                    title={browserTitle}
                    startPath={browserStartPath}
                    mode={browserMode}
                    onSelect={onBrowserSelect}
                />
            )}

            {view === 'vm-info' && (
                <VMInfoPanel
                    vmName={activeVm}
                    info={vmInfoData}
                    onBack={() => setView('main')}
                />
            )}

            {message && (
                <Box marginTop={1} paddingX={1} borderStyle="single" borderColor="yellow">
                    <Text>{message}</Text>
                </Box>
            )}

            <Box marginTop={1}>
                <Text dimColor>{view === 'auth' ? 'Press Ctrl+C to quit' : 'Press Q to quit'}</Text>
            </Box>
        </Box>
    );
};

export default App;
