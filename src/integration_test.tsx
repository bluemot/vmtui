import React from 'react';
import { render } from 'ink-testing-library';
import { App } from './App_component.js';
import * as fs from 'fs/promises';
import * as system from './system.js';

async function test() {
    console.log("Starting Real-System Integration Test for vm22...");

    const mockVms = {
        "vm22": {
            "dir": "/home/tom/vmtui/vms/vm22",
            "host_share": "/home/tom/driver_projects",
            "installing": false
        }
    };
    await fs.writeFile('vms.json', JSON.stringify(mockVms, null, 4));

    const { lastFrame, stdin } = render(<App />);
    await new Promise(r => setTimeout(r, 2000));

    const stripAnsi = (str: string) => str.replace(/[\u001b\u009b][[()#;?]*(?:[a-zA-Z\d]*(?:;[-a-zA-Z\d\/#&.:=?%@~_]*)*)?\u0007/g, '');

    // Step 1: Force Select VM
    console.log("Navigating to Switch VM...");
    stdin.write('\u001B[B'); // 1->2
    stdin.write('\u001B[B'); // 2->3
    stdin.write('\u001B[B'); // 3->4
    await new Promise(r => setTimeout(r, 200));
    stdin.write('\r');
    await new Promise(r => setTimeout(r, 1000));

    console.log("Selecting vm22...");
    stdin.write('\r'); // Select first one (vm22)
    await new Promise(r => setTimeout(r, 1000));

    // Wait for poller to get state (VM is likely running now)
    console.log("Waiting for poller (7s)...");
    await new Promise(r => setTimeout(r, 7000));
    
    let frame = stripAnsi(lastFrame() || "");
    console.log("--- Frame after waiting ---");
    console.log(frame);

    if (frame.includes('Active VM: vm22')) {
        const stateMatch = frame.match(/Status: \[(.*?)\]/);
        const state = stateMatch ? stateMatch[1] : "unknown";
        console.log(`✅ VM Selected. Current State: ${state}`);

        if (state.includes('running')) {
            console.log("VM is already running. Testing Viewer launch...");
            // Viewer is option 8 (7 downs)
            for(let i=0; i<7; i++) stdin.write('\u001B[B');
            stdin.write('\r');
            await new Promise(r => setTimeout(r, 1000));
            console.log(stripAnsi(lastFrame() || ""));
        } else {
            console.log("Testing Start command...");
            // Start is option 7 (6 downs)
            for(let i=0; i<6; i++) stdin.write('\u001B[B');
            stdin.write('\r');
            await new Promise(r => setTimeout(r, 5000));
            console.log("--- After Start Command ---");
            console.log(stripAnsi(lastFrame() || ""));
        }
    }

    process.exit(0);
}

test();
