# VMTUI Porting Project (Python to TypeScript)

## Project Goal
This project aims to port the functionality of `vmtui.py` (Python) to a TypeScript-based implementation.

## Technical Stack
- **Language:** TypeScript
- **UI Framework:** [Ink](https://github.com/vadimdemedes/ink) (React-based CLI UI)
- **Environment:** Node.js

## Feature Checklist (from vmtui.py)

### 1. Host Management
- [x] Setup Host Environment (Package installation: qemu, libvirt, etc.)
- [x] System Health Check (libvirtd status, network start)
- [x] Configure Host Share Directory (Global/Per-VM)
- [x] Permission Fixes (ACLs for `libvirt-qemu` user)
- [ ] Configure NSS Libvirt (`/etc/nsswitch.conf`) - *Installed but not configured*

### 2. VM Lifecycle Operations
- [x] Start VM (with auto-fix for Spice/AppArmor issues)
- [x] Stop VM (Force Stop / Destroy)
- [x] Host Pause / Resume VM (virsh suspend/resume)
- [x] Hibernate (ManagedSave)
- [ ] Guest Suspend (S3 - RAM) - *UI Entry exists, implementation pending*
- [ ] Guest Hibernate (S4 - Disk) - *UI Entry exists, implementation pending*
- [ ] Wakeup (dompmwakeup)

### 3. VM Creation Wizard
- [x] Linux Cloud-Init Auto-Installation (Ubuntu/Debian/Fedora/CentOS/Rocky)
- [x] Custom Disk Size
- [ ] Windows ISO Installation (with VirtIO injection) - *Wizard UI exists, implementation pending*
- [ ] Linux ISO Manual Installation - *Wizard UI exists, implementation pending*
- [ ] Network Configuration (NAT, Bridge, Dual)
- [ ] Auto-downloading base images / VirtIO ISO

### 4. VM Management
- [x] Switch Active VM
- [x] Import / Rescue Existing VM Directory
- [x] USB Device Manager (Attach/Detach)
- [x] Background State Poller (Status updates every 5s)
- [ ] Duplicate/Clone VM - *Menu entry exists, logic missing*
- [ ] Resize VM Disk - *Current implementation incorrectly maps 'resize' to 'resume'*
- [ ] Adjust RAM / CPU Resources
- [ ] CD-ROM/ISO Manager (Insert/Eject)
- [ ] Delete Active VM

### 5. Access & Monitoring
- [x] Console Access (Text-based via `virsh console`)
- [x] Viewer Access (Graphical - `virt-viewer`)
- [x] Tail Install/Boot Logs (via `tail -f`)
- [ ] Zombie VM Detection & Cleanup

## Progress Tracking
- UI Framework (Ink) - [x] Initial Setup
- Main Menu - [x] Fully Mapped with Sidebar-style Category Navigation
- File Browser - [x] Implemented for directory/file selection
- Linux Cloud VM - [x] Fully Implemented
- USB Manager - [x] Fully Implemented
