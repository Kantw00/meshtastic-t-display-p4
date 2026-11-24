# PlatformIO post script of the ESP32-C6 co-processor firmware.
#
# 1. After each build the flashable image set is copied to ../c6_fw with a manifest.json
#    (offsets, sizes, MD5s). ../p4-flasher embeds that directory.
# 2. "pio run -t upload" additionally writes 0xFF over the nvs partition, so that settings of the
#    firmware that was on the C6 before (ESP-AT from the factory) do not survive.

import csv
import hashlib
import json
import re
import shutil
from pathlib import Path

Import("env")  # noqa: F821

project_dir = Path(env.subst("$PROJECT_DIR"))
build_dir = Path(env.subst("$BUILD_DIR"))
export_dir = project_dir.parent / "c6_fw"

# Names the image set had when it came out of idf.py; kept so that c6_fw looks the same either way
EXPORT_NAMES = {
    "partitions.bin": "partition-table.bin",
    env.subst("${PROGNAME}.bin"): "network_adapter.bin",
}


def firmware_version():
    header = (project_dir / "main" / "esp_hosted_coprocessor_fw_ver.h").read_text()
    parts = [re.search(r"PROJECT_VERSION_%s_1\s+(\d+)" % key, header) for key in ("MAJOR", "MINOR", "PATCH")]
    return ".".join(m.group(1) for m in parts) if all(parts) else "unknown"


def partition_size(text):
    text = text.strip()
    factor = {"K": 1024, "M": 1024 * 1024}.get(text[-1].upper(), 1)
    return int(text[:-1] if factor > 1 else text, 0) * factor


def nvs_partition():
    with open(env.subst("$PARTITIONS_TABLE_CSV"), newline="") as fp:
        rows = csv.reader(line for line in fp if line.strip() and not line.lstrip().startswith("#"))
        for row in rows:
            fields = [field.strip() for field in row]
            if len(fields) >= 5 and fields[1] == "data" and fields[2] == "nvs":
                return int(fields[3], 0), partition_size(fields[4])
    return None


# Read now: the upload flags added below must not end up in the exported set
flash_images = [(offset, Path(env.subst(path))) for offset, path in env.get("FLASH_EXTRA_IMAGES", [])]


def export_images(source, target, env):
    images = flash_images + [(env.subst("$ESP32_APP_OFFSET"), build_dir / env.subst("${PROGNAME}.bin"))]
    export_dir.mkdir(exist_ok=True)
    entries = []
    for offset, path in sorted(images, key=lambda image: int(str(image[0]), 0)):
        name = EXPORT_NAMES.get(path.name, path.name)
        shutil.copyfile(path, export_dir / name)
        data = path.read_bytes()
        entries.append(
            {"file": name, "offset": hex(int(str(offset), 0)), "size": len(data), "md5": hashlib.md5(data).hexdigest()}
        )
    manifest = {"chip": "esp32c6", "version": "esp-hosted " + firmware_version(), "images": entries}
    (export_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("C6 images: %d files and manifest.json written to %s" % (len(entries), export_dir))


env.AddPostAction("$BUILD_DIR/${PROGNAME}.bin", export_images)

nvs = nvs_partition()
if nvs:
    blank = build_dir / "nvs_blank.bin"
    build_dir.mkdir(parents=True, exist_ok=True)
    blank.write_bytes(b"\xff" * nvs[1])
    env.Append(UPLOADERFLAGS=[hex(nvs[0]), str(blank)])
