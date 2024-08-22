#!/usr/bin/env bash

# ===========================================================
# Copyright (C) 2024 Blankhaus Ltd. <frederick@blankhaus.com>
# ===========================================================

KLIPPER_PATH="${HOME}/klipper"

set -eu
export LC_ALL=C

function preflight_checks {
    if [ "$EUID" -eq 0 ]; then
        echo "[PRE-CHECK] This script must not be run as root!"
        echo
        exit -1
    fi

    if [ "$(sudo systemctl list-units --full -all -t service --no-legend | grep -F 'klipper.service')" ]; then
        echo "[PRE-CHECK] Klipper service found!"
    else
        echo "[ERROR] Klipper service not found, please install Klipper first!"
        echo
        exit -1
    fi

    echo "[PRE-CHECK] Ready to uninstall plugin."
    
    local uninstall_answer
    read < /dev/tty -rp "[PRE-CHECK] Do you want to continue? [Y/n] " uninstall_answer
    if [[ -z "$uninstall_answer" ]]; then
        uninstall_answer="n"
    fi
    uninstall_answer="${uninstall_answer,,}"

    if [[ "$uninstall_answer" =~ ^(yes|y)$ ]]; then
        echo "[PRE-CHECK] Uninstallation confirmed!"
    else
        echo "[PRE-CHECK] Uninstallation canceled!"
        echo
        exit -1
    fi
}

function uninstall_plugin {
    printf "[UNINSTALL] Removing plugin files from Klipper... "
    
    if [ -f "${KLIPPER_PATH}/klippy/plugins/filter_monitor.py" ]; then
        rm -f ${KLIPPER_PATH}/klippy/plugins/filter_monitor.py
    fi

    if [ -f "${KLIPPER_PATH}/klippy/extras/filter_monitor.py" ]; then
        rm -f ${KLIPPER_PATH}/klippy/extras/filter_monitor.py
    fi

    echo "OK!"
}

function restart_klipper {
    printf "[POST-UNINSTALL] Restarting Klipper... "
    sudo systemctl restart klipper
    echo "OK!"
}

echo
echo "______ _             _    _                     "
echo "| ___ \ |           | |  | |                    "
echo "| |_/ / | __ _ _ __ | | _| |__   __ _ _   _ ___ "
echo "| ___ \ |/ _' | '_ \| |/ / '_ \ / _' | | | / __|"
echo "| |_/ / | (_| | | | |   <| | | | (_| | |_| \__ \\"
echo "\____/|_|\__,_|_| |_|_|\_\_| |_|\__,_|\__,_|___/"
echo
echo "================================================"
echo "                 FILTER MONITOR                 "
echo "------------------------------------------------"
echo "This Klipper plugin monitors the runtime of air "
echo "filters (Nevermore, THE FILTER, etc), and       "
echo "triggers notifications and/or executes G-code   "
echo "when threshold conditions, such as max runtime  "
echo "or lifetime hours are met. These monitoring     "
echo "checks also occur on pre-defined system events  "
echo "and keep track of total fan runtime.            "
echo "================================================"
echo

preflight_checks
uninstall_plugin
restart_klipper

echo "[POST-UNINSTALL] Uninstallation complete!"
echo
