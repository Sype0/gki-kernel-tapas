#!/usr/bin/env python3
"""Check that the phone's vendor kernel modules will load on a kernel build.

  check_vendor_abi.py --symvers vmlinux.symvers [--gki-module zram.ko ...] PATH...

PATH is a vendor module (.ko, .ko.xz, .ko.gz) or a directory searched for them.
Every symbol a vendor module imports (its __versions table) must be exported
by the kernel with the same CRC, or be exported by another module (vendor or
GKI). The modules' vermagic flags must also match the GKI modules'. Exits 1 if
any module would fail to load.
"""
import argparse
import gzip
import lzma
import os
import struct
import sys

MODVERSION_ENTRY = 64  # struct modversion_info on 64-bit: unsigned long crc + char name[56]


def read_module(path):
    data = open(path, "rb").read()
    if path.endswith(".xz"):
        return lzma.decompress(data)
    if path.endswith(".gz"):
        return gzip.decompress(data)
    return data


def elf_sections(elf):
    if elf[:4] != b"\x7fELF" or elf[4] != 2 or elf[5] != 1:
        raise ValueError("not a little-endian ELF64 file")
    shoff = struct.unpack_from("<Q", elf, 0x28)[0]
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", elf, 0x3A)
    headers = [struct.unpack_from("<IIQQQQIIQQ", elf, shoff + i * shentsize) for i in range(shnum)]
    names_off = headers[shstrndx][4]
    sections = {}
    for name_off, sh_type, _, _, offset, size, *_ in headers:
        start = names_off + name_off
        name = elf[start:elf.index(b"\0", start)].decode()
        sections[name] = b"" if sh_type == 8 else elf[offset:offset + size]  # 8 = SHT_NOBITS
    return sections


class Module:
    def __init__(self, path):
        self.path = path
        sec = elf_sections(read_module(path))
        modinfo = dict(
            kv.split("=", 1) for kv in sec.get(".modinfo", b"").decode(errors="replace").split("\0") if "=" in kv
        )
        self.name = modinfo.get("name", os.path.basename(path).split(".")[0])
        self.vermagic = modinfo.get("vermagic", "")
        self.imports = {}
        versions = sec.get("__versions", b"")
        for i in range(0, len(versions) - MODVERSION_ENTRY + 1, MODVERSION_ENTRY):
            crc = struct.unpack_from("<Q", versions, i)[0] & 0xFFFFFFFF
            sym = versions[i + 8:i + MODVERSION_ENTRY].split(b"\0")[0].decode()
            self.imports[sym] = crc
        self.exports = {s.decode() for s in sec.get("__ksymtab_strings", b"").split(b"\0") if s}


def load_symvers(path):
    crcs = {}
    for line in open(path):
        fields = line.rstrip("\n").split("\t")
        if len(fields) >= 2:
            crcs[fields[1]] = int(fields[0], 16)
    return crcs


def find_modules(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in sorted(files):
                    if f.endswith((".ko", ".ko.xz", ".ko.gz")):
                        yield os.path.join(root, f)
        else:
            yield p


def flags(vermagic):
    # The release string is skipped when modversions are on; the rest must match.
    return vermagic.split(" ", 1)[1] if " " in vermagic else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symvers", required=True, help="vmlinux.symvers of the kernel build")
    ap.add_argument("--gki-module", action="append", default=[], help="GKI module built with the kernel (repeatable)")
    ap.add_argument("paths", nargs="+")
    args = ap.parse_args()

    kernel = load_symvers(args.symvers)
    gki = [Module(p) for p in args.gki_module]
    vendor = [Module(p) for p in find_modules(args.paths)]
    module_exports = set().union(*(m.exports for m in gki + vendor))
    expected_flags = flags(gki[0].vermagic) if gki else None

    errors = []
    checked = from_kernel = 0
    for m in vendor:
        if expected_flags is not None and flags(m.vermagic) != expected_flags:
            errors.append(f"{m.name}: vermagic flags {flags(m.vermagic)!r} != {expected_flags!r}")
        for sym, crc in sorted(m.imports.items()):
            checked += 1
            if sym in kernel:
                from_kernel += 1
                if kernel[sym] != crc:
                    errors.append(f"{m.name}: {sym} CRC 0x{crc:08x}, kernel has 0x{kernel[sym]:08x}")
            elif sym not in module_exports:
                errors.append(f"{m.name}: {sym} is not exported by the kernel or any module")

    print(f"{len(vendor)} vendor modules, {checked} imported symbols "
          f"({from_kernel} from the kernel, checked against its {len(kernel)} exports)")
    for e in errors:
        print("ERROR:", e)
    print("RESULT:", "FAIL" if errors else "OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
