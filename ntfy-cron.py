#!/usr/bin/env python3

import subprocess
import shutil
import os
from pathlib import Path
import datetime
import socket

# Config
##todo make this paragraph a .env file type thing. 
NTFY_URL = "https://your.ntfy.server"
DIRS_TO_CHECK = ["/etc", "/var/log", "/home"]
OK_LEVEL = 70  # In percent, below which is OK
WARNING_LEVEL = OK_LEVEL - 10  # 10% under OK is warning
MIN_FREE_SPACE_GB = 5  # Minimum free space required (in GB)
ALERT_DAYS = [0, 1, 2, 3, 4, 5, 6, 7]  # Days to alert sun, mon, etc

def run(cmd):
    try:
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
        return result.stdout.strip()
    except Exception:
        return ""

def get_disks():
    lines = run(["lsblk", "-dn", "-o", "NAME,TYPE"]).splitlines()
    return [line.split()[0] for line in lines
            if line.split()[1] == "disk" and "boot" not in line.split()[0]]

def get_disk_size_bytes(dev):
    size_str = run(["lsblk", "-bn", "-o", "SIZE", f"/dev/{dev}"])
    if size_str.isdigit():
        return int(size_str)

    sys_path = f"/sys/block/{dev}/size"
    try:
        with open(sys_path, "r") as f:
            sectors = int(f.read().strip())
            return sectors * 512  # 512 bytes per sector
    except Exception:
        return None

def get_used_bytes(dev):
    used = 0
    partitions = run(["lsblk", "-ln", "-o", "NAME", f"/dev/{dev}"]).splitlines()
    for part in partitions:
        if part.strip() == dev:
            continue
        mp = run(["lsblk", "-n", "-o", "MOUNTPOINT", f"/dev/{part}"]).splitlines()
        if mp and mp[0]:
            df_out = run(["df", "--output=used", "-B1", mp[0]])
            try:
                used += int(df_out.splitlines()[1])
            except (IndexError, ValueError):
                continue
    return used

def format_size(bytes_val):
    for unit in ['B', 'K', 'M', 'G', 'T']:
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}P"

def get_dir_sizes(dirs):
    results = []
    for d in dirs:
        if os.path.isdir(d):
            du_output = subprocess.run(["du", "-sh", d], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True).stdout.strip()
            if du_output:
                size = du_output.split()[0]
                results.append(f"{d}: {size}")
            else:
                results.append(f"{d}: Error getting size")
        else:
            results.append(f"{d}: Not found")
    return results

def send_ntfy(message):
    if shutil.which("curl") is None:
        print("curl not installed. Cannot send to ntfy.")
        print(message)
        return
    subprocess.run(["curl", "-d", message, NTFY_URL])

def check_emoji(percent):
    if percent <= OK_LEVEL:
        return "✅"  # Green, OK
    elif percent <= WARNING_LEVEL:
        return "🟠"  # Orange, Warning
    else:
        return "🔴"  # Red, Critical

def should_alert_today():
    today = datetime.datetime.today().weekday()
    return today in ALERT_DAYS

def get_hostname_and_ip():
    # Get the hostname
    hostname = socket.gethostname()

    # Get the local IP address (assuming the default interface)
    ip = run(["hostname", "-I"]).split()[0]  # First IP from hostname -I

    return hostname, ip

# Build report
hostname, ip = get_hostname_and_ip()

# Check the worst disk usage to determine the first line emoji
worst_usage_percent = 0
for disk in get_disks():
    size = get_disk_size_bytes(disk)
    used = get_used_bytes(disk)
    if size and size > 0:
        percent = used / size * 100
        if percent > worst_usage_percent:
            worst_usage_percent = percent

# Determine the emoji for the first line based on the worst usage
first_line_emoji = check_emoji(worst_usage_percent)

# Report initialization
report = [f"{first_line_emoji}=== Server Info ==={first_line_emoji}\nHost: {hostname} - IP: {ip}"]

# Disk usage summary
report.append("\n=== Disk Usage Summary ===")
for disk in get_disks():
    size = get_disk_size_bytes(disk)
    used = get_used_bytes(disk)
    if size and size > 0:
        percent = used / size * 100
        used_gb = used / (1024**3)
        size_gb = size / (1024**3)
        emoji = check_emoji(percent)
        report.append(f"{emoji} /dev/{disk}:\t{used_gb:.2f}G / {size_gb:.2f}G\t({percent:.2f}% used)")
    else:
        report.append(f"/dev/{disk}: Unable to get size")

# Directory sizes
report.append("\n=== Directory Sizes ===")
report.extend(get_dir_sizes(DIRS_TO_CHECK))

# Send it only if it's the right day
if should_alert_today():
    send_ntfy("\n".join(report))
