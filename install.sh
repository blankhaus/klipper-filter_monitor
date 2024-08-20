#!/usr/bin/env bash

# ===========================================================
# Copyright (C) 2024 Blankhaus Ltd. <frederick@blankhaus.com>
# ===========================================================

KLIPPER_PATH="${HOME}/klipper"
GIT_PATH="${HOME}/klipper-filter_monitor"

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

    echo "[PRE-CHECK] Ready to install plugin."
    
    local install_answer
    read < /dev/tty -rp "[PRE-CHECK] Do you want to continue? [Y/n] " install_answer
    if [[ -z "$install_answer" ]]; then
        install_answer="n"
    fi
    install_answer="${install_answer,,}"

    if [[ "$install_answer" =~ ^(yes|y)$ ]]; then
        echo "[PRE-CHECK] Installation confirmed!"
    else
        echo "[PRE-CHECK] Installation canceled!"
        echo
        exit -1
    fi
}

function check_download {
    local gitdirname gitbasename
    gitdirname="$(dirname ${GIT_PATH})"
    gitbasename="$(basename ${GIT_PATH})"

    if [ ! -d "${GIT_PATH}" ]; then
        echo "[GIT] Cloning repository..."
        if git -C $gitdirname clone https://github.com/blankhaus/klipper-filter_monitor.git $gitbasename; then
            echo "[GIT] Cloning complete!"
        else
            echo "[GIT] Cloning failed!"
            echo
            exit -1
        fi
    else
        echo "[GIT] Repository already exists!"
    fi
}

function install_plugin {
    printf "[INSTALL] Linking plugin to Klipper... "

    if [ -d "${KLIPPER_PATH}/klippy/plugins" ]; then
        ln -fsn ${GIT_PATH}/filter_monitor.py ${KLIPPER_PATH}/klippy/plugins
    else
        ln -fsn ${GIT_PATH}/filter_monitor.py ${KLIPPER_PATH}/klippy/extras
    fi

    chmod +x ${GIT_PATH}/install.sh
    chmod +x ${GIT_PATH}/uninstall.sh

    echo "OK!"
}

function restart_klipper {
    printf "[POST-INSTALL] Restarting Klipper... "
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
echo "triggers notifications and/or executes GCODE    "
echo "when threshold conditions, such as max runtime  "
echo "or lifetime hours, are met.                     "
echo "================================================"
echo

preflight_checks
check_download
install_plugin
restart_klipper

echo "[POST-INSTALL] Installation complete!"
echo
