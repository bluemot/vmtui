import React from 'react';
import { render } from 'ink-testing-library';
import { App } from './App_component.js';
import * as fs from 'fs/promises';

async function test() {
    const mockVms = {
        "test-vm": {
            "dir": "/tmp/vms/test-vm",
            "host_share": "/tmp/share",
            "installing": false
        }
    };
    await fs.writeFile('vms.json', JSON.stringify(mockVms, null, 4));

    const { lastFrame, stdin } = render(<App />);
    await new Promise(r => setTimeout(r, 1000));

    console.log("Navigating to Switch VM...");
    for (let i = 0; i < 3; i++) {
        stdin.write('\u001B[B');
        await new Promise(r => setTimeout(r, 200));
    }
    stdin.write('\r');
    await new Promise(r => setTimeout(r, 1000));

    if (lastFrame()?.includes('Select VM')) {
        stdin.write('\r');
        await new Promise(r => setTimeout(r, 1000));
        
        const frame = lastFrame() || "";
        const stripAnsi = (str: string) => str.replace(/[\u001b\u009b][[()#;?]*(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d\/#&.:=?%@~_]*)*)?\u0007/g, '');
        const cleanFrame = stripAnsi(frame);
        
        console.log("--- Clean Frame ---");
        console.log(cleanFrame);

        // Check for specific markers
        const hasVm = cleanFrame.includes('test-vm');
        const hasActiveLabel = cleanFrame.includes('Active VM:');
        
        console.log(`Has 'test-vm': ${hasVm}`);
        console.log(`Has 'Active VM:': ${hasActiveLabel}`);
        
        if (hasVm && hasActiveLabel) {
            console.log("✅ SUCCESS");
            process.exit(0);
        }
    }

    console.log("❌ FAILURE");
    process.exit(1);
}

test();
