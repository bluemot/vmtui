# 放在 Host 的 .bashrc 中
# 用法: kvm-usb-attach driver-dev-vm 0951 1666
function kvm-usb-attach() {
    VM=$1
    VID=$2
    PID=$3
    XML="<hostdev mode='subsystem' type='usb' managed='yes'><source><vendor id='0x$VID'/><product id='0x$PID'/></source></hostdev>"
    echo "$XML" > /tmp/usb_pass.xml
    virsh attach-device "$VM" /tmp/usb_pass.xml --live
    echo "Attached USB ($VID:$PID) to $VM"
}

# 用法: kvm-usb-detach driver-dev-vm 0951 1666
function kvm-usb-detach() {
    VM=$1
    VID=$2
    PID=$3
    XML="<hostdev mode='subsystem' type='usb' managed='yes'><source><vendor id='0x$VID'/><product id='0x$PID'/></source></hostdev>"
    echo "$XML" > /tmp/usb_pass.xml
    virsh detach-device "$VM" /tmp/usb_pass.xml --live
    echo "Detached USB ($VID:$PID) from $VM"
}
