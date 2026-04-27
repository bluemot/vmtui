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
- [ ] Configure NSS Libvirt (`/etc/nsswitch.conf`)
- [x] Configure Host Share Directory (Global/Per-VM)
- [x] System Health Check (libvirtd status, network start)
- [x] Permission Fixes (ACLs for `libvirt-qemu` user)

### 2. VM Lifecycle Operations
- [x] Start VM
- [x] Stop VM (Force Stop / Destroy)
- [x] Pause / Resume VM
- [x] Hibernate (ManagedSave)
- [ ] Guest Suspend (S3 - RAM)
- [ ] Guest Hibernate (S4 - Disk)
- [ ] Wakeup (dompmwakeup)

### 3. VM Creation Wizard
- [ ] Windows ISO Installation (with VirtIO injection)
- [x] Linux Cloud-Init Auto-Installation (Initial implementation)
- [ ] Linux ISO Manual Installation
- [ ] Network Configuration (NAT, Bridge, Dual)
- [ ] Custom Disk Size & Path
- [ ] Auto-downloading base images / VirtIO ISO

### 4. VM Management
- [x] Switch Active VM
- [ ] Duplicate/Clone VM (with Linux identity auto-fix: Hostname, Machine-ID)
- [ ] Import / Rescue Existing VM Directory
- [ ] Resize VM Disk
- [ ] Adjust RAM / CPU Resources
- [ ] USB Device Manager (Attach/Detach)
- [ ] CD-ROM/ISO Manager (Insert/Eject)
- [x] Background State Poller (Status updates)

### 5. Access & Monitoring
- [ ] Console Access (Text-based)
- [x] Viewer Access (Graphical - virt-viewer)
- [ ] Tail Install/Boot Logs
- [ ] Zombie VM Detection & Cleanup

## Progress Tracking
- UI Framework (Ink) - [x] Initial Setup
- Main Menu - [x] Fully Mapped
- File Browser - [x] Implemented
- Linux Cloud VM - [x] Partially Implemented
