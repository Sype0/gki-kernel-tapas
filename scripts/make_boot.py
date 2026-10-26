#!/usr/bin/env python3
"""Put a new kernel into the boot.img the phone already runs.

  make_boot.py --base boot.img --kernel Image --key testkey.pem --avbtool avbtool.py -o out.img
  make_boot.py --base boot.img --extract-kernel Image.old

The boot header (OS version, security patch level, cmdline) is copied from
--base and only the kernel size changes. The AVB hash footer is recreated with
the base image's partition size, algorithm, rollback index, properties and
salt, so the bootloader and KeyMint see the same version info as before.
Building from the base image's own kernel reproduces the base image exactly.
"""
import argparse
import os
import struct
import subprocess
import sys
import tempfile

PAGE = 4096
ALGORITHMS = {1: "SHA256_RSA2048", 2: "SHA256_RSA4096", 3: "SHA256_RSA8192",
              4: "SHA512_RSA2048", 5: "SHA512_RSA4096", 6: "SHA512_RSA8192"}


def parse_base(img):
    hdr = img[:PAGE]
    if hdr[:8] != b"ANDROID!" or struct.unpack_from("<I", hdr, 40)[0] != 4:
        sys.exit("base is not a v4 boot image")
    kernel_size, ramdisk_size = struct.unpack_from("<II", hdr, 8)
    if ramdisk_size:
        sys.exit("base boot image has a ramdisk; only kernel-only (GKI) boot images are supported")
    footer = img[-64:]
    if footer[:4] != b"AVBf":
        sys.exit("base has no AVB footer")
    _, _, _, vb_off, vb_size = struct.unpack(">IIQQQ", footer[4:36])
    v = img[vb_off:vb_off + vb_size]
    auth_size, aux_size, alg = struct.unpack(">QQI", v[12:32])
    pk_off, pk_size = struct.unpack(">QQ", v[64:80])
    desc_off, desc_size, rollback, flags, rb_loc = struct.unpack(">QQQII", v[96:128])
    aux = v[256 + auth_size:256 + auth_size + aux_size]
    info = {"header": hdr, "kernel": img[PAGE:PAGE + kernel_size], "partition_size": len(img),
            "algorithm": alg, "rollback_index": rollback, "flags": flags, "rollback_index_location": rb_loc,
            "release": v[128:176].split(b"\0")[0].decode(), "public_key": aux[pk_off:pk_off + pk_size],
            "props": [], "hash": None}
    d = aux[desc_off:desc_off + desc_size]
    i = 0
    while i + 16 <= len(d):
        tag, n = struct.unpack(">QQ", d[i:i + 16])
        body = d[i + 16:i + 16 + n]
        if tag == 0:  # property
            kl, vl = struct.unpack(">QQ", body[:16])
            info["props"].append((body[16:16 + kl].decode(), body[17 + kl:17 + kl + vl].decode()))
        elif tag == 2:  # hash
            algo = body[8:40].split(b"\0")[0].decode()
            pl, sl, dl = struct.unpack(">III", body[40:52])
            name = body[116:116 + pl].decode()
            salt = body[116 + pl:116 + pl + sl]
            info["hash"] = (name, algo, salt.hex())
        else:
            sys.exit(f"base vbmeta has an unsupported descriptor (tag {tag})")
        i += 16 + n
    if info["hash"] is None:
        sys.exit("base vbmeta has no hash descriptor")
    return info


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True)
    ap.add_argument("--kernel")
    ap.add_argument("--key")
    ap.add_argument("--avbtool")
    ap.add_argument("-o", "--output")
    ap.add_argument("--extract-kernel", metavar="FILE", help="write the base image's kernel to FILE and exit")
    args = ap.parse_args()

    base = parse_base(open(args.base, "rb").read())
    if args.extract_kernel:
        open(args.extract_kernel, "wb").write(base["kernel"])
        return
    if not (args.kernel and args.key and args.avbtool and args.output):
        ap.error("--kernel, --key, --avbtool and -o are required")
    if base["algorithm"] not in ALGORITHMS:
        sys.exit(f"base vbmeta algorithm {base['algorithm']} is not supported")

    avbtool = [sys.executable, "-I", args.avbtool]
    pubkey = subprocess.run(avbtool + ["extract_public_key", "--key", args.key, "--output", "/dev/stdout"],
                            check=True, capture_output=True).stdout
    if pubkey != base["public_key"]:
        sys.exit("--key is not the key the base boot image was signed with")

    kernel = open(args.kernel, "rb").read()
    hdr = bytearray(base["header"])
    struct.pack_into("<I", hdr, 8, len(kernel))
    with open(args.output, "wb") as f:
        f.write(hdr + kernel + b"\0" * ((-len(kernel)) % PAGE))

    name, algo, salt = base["hash"]
    cmd = avbtool + ["add_hash_footer", "--image", args.output, "--partition_name", name,
                     "--partition_size", str(base["partition_size"]), "--hash_algorithm", algo, "--salt", salt,
                     "--algorithm", ALGORITHMS[base["algorithm"]], "--key", args.key,
                     "--rollback_index", str(base["rollback_index"]),
                     "--rollback_index_location", str(base["rollback_index_location"]),
                     "--flags", str(base["flags"])]
    for k, v in base["props"]:
        cmd += ["--prop", f"{k}:{v}"]
    subprocess.run(cmd, check=True)
    # verify_image looks the hashed image up as <partition name>.img next to the one it checks
    with tempfile.TemporaryDirectory() as tmp:
        link = os.path.join(tmp, f"{name}.img")
        os.symlink(os.path.abspath(args.output), link)
        subprocess.run(avbtool + ["verify_image", "--image", link, "--key", args.key], check=True)

    out = parse_base(open(args.output, "rb").read())
    for field in ("partition_size", "algorithm", "rollback_index", "flags", "rollback_index_location",
                  "release", "public_key", "props"):
        if out[field] != base[field]:
            sys.exit(f"{field} differs from the base image: {out[field]!r} != {base[field]!r}")
    if out["header"][:8] + out["header"][12:] != base["header"][:8] + base["header"][12:]:
        sys.exit("boot header differs from the base image beyond the kernel size")
    print(f"{args.output}: kernel {len(kernel)} bytes; header, AVB props, rollback index and key match {args.base}")


if __name__ == "__main__":
    main()
