#!/usr/bin/env python3
"""
Build (and verify) a testkey-signed flashable zip for Allwinner EPD106
readers -- Xiaomi DuoKan MiReader / Moaan -- device `virgo-perf1`.

Why this works
--------------
The stock firmware is signed with the *AOSP public test key*: the device's
/system/etc/security/otacerts.zip equals AOSP 8.1 `testkey.x509.pem`. Stock
recovery therefore accepts any update.zip signed with the matching private
key, via  recovery -> "Apply update from ADB" -> `adb sideload <zip>`.

Recovery only verifies the **whole-file** signature: a PKCS7 DER blob appended
to the zip comment, covering [file start, EOCD+20). That is exactly what
`signapk -w` emits ("signed by SignApk" + NUL + DER).

Requirements
------------
* JDK **8** -- signapk reaches into `sun.security.pkcs`, which JDK 9+ no
  longer exports. (Temurin 8 works.)
* `signapk-1.0.jar`, `testkey.pk8`, `testkey.x509.pem`
* a template zip providing the recovery-accepted
  `update-binary` / `otacert` / `metadata`
  (e.g. `kernel_flashing_template.zip` from delbertbeta/edp106)

Usage
-----
  build_zips.py \
      --template kernel_flashing_template.zip \
      --updater-script examples/remove-package-updater-script \
      --java /path/to/jdk8/bin/java \
      --signapk signapk-1.0.jar \
      --cert testkey.x509.pem --key testkey.pk8 \
      --out my_fix_signed.zip

  # verify an existing signed zip
  build_zips.py --verify my_fix_signed.zip
"""
import argparse
import os
import struct
import subprocess
import sys
import zipfile

MARKER = b"signed by SignApk"


def verify(zip_path):
    """Check the whole-file PKCS7 signature that stock recovery looks for."""
    with open(zip_path, "rb") as fh:
        data = fh.read()
    i = data.rfind(b"PK\x05\x06")
    if i < 0:
        print("%s: NOT a zip (no EOCD)" % zip_path)
        return False
    comment_len = struct.unpack("<H", data[i + 20:i + 22])[0]
    if comment_len == 0:
        print("%s: FAIL - no zip comment, so no whole-file signature" % zip_path)
        return False
    comment = data[len(data) - comment_len:]
    if not comment.startswith(MARKER):
        print("%s: FAIL - comment does not start with %r" % (zip_path, MARKER))
        return False
    blob = comment[len(MARKER) + 1:]
    ok = blob[:2] == b"\x30\x82"
    print("%s: comment=%d bytes, payload=%d bytes, DER PKCS7=%s -> %s"
          % (zip_path, comment_len, len(blob), ok, "OK" if ok else "FAIL"))
    return ok


def build(args):
    missing = [p for p in (args.template, args.updater_script, args.java,
                           args.signapk, args.cert, args.key)
               if not os.path.isfile(p)]
    if missing:
        sys.exit("missing input(s): " + ", ".join(missing))

    with open(args.updater_script, "rb") as fh:
        script = fh.read()

    stage = args.out + ".unsigned"
    with zipfile.ZipFile(args.template) as src, \
            zipfile.ZipFile(stage, "w", zipfile.ZIP_DEFLATED) as dst:
        replaced = False
        for entry in src.infolist():
            data = src.read(entry.filename)
            if entry.filename.endswith("updater-script"):
                data = script
                replaced = True
            dst.writestr(entry, data)
    if not replaced:
        os.remove(stage)
        sys.exit("template has no META-INF/.../updater-script entry")

    if os.path.exists(args.out):
        os.remove(args.out)
    # -w == sign the whole file (PKCS7 in the zip comment), which is what
    # stock recovery actually verifies.
    proc = subprocess.run(
        [args.java, "-jar", args.signapk, "-w", args.cert, args.key,
         stage, args.out],
        capture_output=True, text=True)
    os.remove(stage)
    if proc.returncode != 0:
        sys.exit("signapk failed (rc=%d)\n%s" % (proc.returncode, proc.stderr))
    print("signed -> %s (%d bytes)" % (args.out, os.path.getsize(args.out)))
    return verify(args.out)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", help="template zip with update-binary/otacert/metadata")
    ap.add_argument("--updater-script", help="updater-script to substitute in")
    ap.add_argument("--java", default="java", help="JDK 8 java executable")
    ap.add_argument("--signapk", default="signapk-1.0.jar")
    ap.add_argument("--cert", default="testkey.x509.pem")
    ap.add_argument("--key", default="testkey.pk8")
    ap.add_argument("--out", help="output signed zip")
    ap.add_argument("--verify", metavar="ZIP", help="only verify an existing zip")
    args = ap.parse_args()

    if args.verify:
        sys.exit(0 if verify(args.verify) else 1)
    if not (args.template and args.updater_script and args.out):
        ap.error("--template, --updater-script and --out are required to build")
    sys.exit(0 if build(args) else 1)


if __name__ == "__main__":
    main()
