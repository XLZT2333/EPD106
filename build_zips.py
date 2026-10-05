#!/usr/bin/env python3
"""Build testkey-signed flashable zips for the EPD106 (virgo-perf1) reader.

Base = toolkit/kernel_flashing_template.zip (stock-recovery-accepted
update-binary + otacert + metadata). We swap in our own updater-script and
re-sign with the AOSP test key, exactly as delbertbeta/edp106 does.
"""
import os, sys, zipfile, subprocess, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
TK = os.path.join(ROOT, "tools", "edp106")
JAVA = None
for base, dirs, files in os.walk(os.path.join(ROOT, "tools", "jdk8")):
    if "java.exe" in files:
        JAVA = os.path.join(base, "java.exe")
        break
assert JAVA, "JDK8 java.exe not found"
print("java:", JAVA)

TEMPLATE = os.path.join(TK, "kernel_flashing_template.zip")
SIGNAPK = os.path.join(TK, "signapk-1.0.jar")
CERT = os.path.join(TK, "testkey.x509.pem")
KEY = os.path.join(TK, "testkey.pk8")
OUTDIR = os.path.join(ROOT, "work")
os.makedirs(OUTDIR, exist_ok=True)

PKG = "com.etang.mt_launcher"

SCRIPTS = {
    # data-preserving: drop the bad launcher, keep everything else
    "fix_keepdata": "\n".join([
        'ui_print("MTLFIX 1: mount system for shell");',
        'mount("ext4", "EMMC", "/dev/block/by-name/system", "/system");',
        'ui_print("MTLFIX 2: mount data (f2fs UDISK)");',
        'mount("f2fs", "EMMC", "/dev/block/by-name/UDISK", "/data");',
        'run_program("/system/bin/sh", "-c", "echo === app === > /cache/mtlfix.log; ls -la /data/app >> /cache/mtlfix.log 2>&1; echo === data === >> /cache/mtlfix.log; ls -la /data/data >> /cache/mtlfix.log 2>&1");',
        'ui_print("MTLFIX 3: removing launcher");',
        'run_program("/system/bin/sh", "-c", "rm -rf /data/app/com.etang.mt_launcher-* /data/data/com.etang.mt_launcher; echo === after === >> /cache/mtlfix.log; ls -la /data/app >> /cache/mtlfix.log 2>&1; sync; echo MTLFIX-REMOVED >> /cache/mtlfix.log");',
        'run_program("/system/bin/sh", "-c", "cp /cache/mtlfix.log /data/local/tmp/mtlfix.log 2>/dev/null; sync");',
        'ui_print("MTLFIX 4: done - safe to reboot");',
    ]),
    # fallback: factory-reset /data (loses user data, guaranteed boot)
    "wipe_data": "\n".join([
        'ui_print("MTLWIPE 1: mounting data");',
        'mount("ext4", "EMMC", "/dev/block/by-name/system", "/system");',
        'mount("f2fs", "EMMC", "/dev/block/by-name/UDISK", "/data");',
        'run_program("/system/bin/sh", "-c", "ls -la /data > /cache/mtlwipe.log 2>&1");',
        'ui_print("MTLWIPE 2: erasing /data");',
        'run_program("/system/bin/sh", "-c", "rm -rf /data/* /data/.[!.]* 2>/dev/null; echo MTLWIPE-DONE >> /cache/mtlwipe.log; sync");',
        'ui_print("MTLWIPE 3: done - safe to reboot");',
    ]),
}

for name, script in SCRIPTS.items():
    stage = os.path.join(OUTDIR, name + "_unsigned.zip")
    with zipfile.ZipFile(TEMPLATE) as src, zipfile.ZipFile(stage, "w", zipfile.ZIP_DEFLATED) as dst:
        for entry in src.infolist():
            data = src.read(entry.filename)
            if entry.filename.endswith("updater-script"):
                data = script.encode("utf-8")
            dst.writestr(entry, data)
    signed = os.path.join(OUTDIR, name + "_signed.zip")
    if os.path.exists(signed):
        os.remove(signed)
    r = subprocess.run([JAVA, "-jar", SIGNAPK, "-w", CERT, KEY, stage, signed],
                       capture_output=True, text=True)
    print(name, "->", os.path.basename(signed), "rc=", r.returncode,
          "size=", os.path.getsize(signed) if os.path.exists(signed) else "MISSING")
    if r.stdout.strip():
        print("   ", r.stdout.strip().splitlines()[-1])
    if r.returncode != 0:
        print("   STDERR:", r.stderr.strip()[:400])
    os.remove(stage)
