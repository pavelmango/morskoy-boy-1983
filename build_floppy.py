#!/usr/bin/env python3
"""
Генератор 1.44 МБ FAT12-образа дискеты «Морской Бой (1983, ПК-ДОС 1.04)»
Архив воспроизводимой инженерии Евгения Валуева (Eugen Valuev Sovereign Retro Archive).

Создает настоящий 1,474,560-байтный образ 3.5" дискеты (MORSKOY_1983_PKDOS.img)
с загрузочным сектором ПК-ДОС 1.04 (16-бит x86 машинный код, выводящий советскую
релятивистскую телеметрию на экран при загрузке с дискеты!) и файловой системой FAT12,
содержащей MORSKOY.BAS, README.MD и INDEX.HTM.
"""

import pathlib
import struct

SECTOR_SIZE = 512
TOTAL_SECTORS = 2880  # 1.44 MB (80 tracks * 2 heads * 18 sectors)
IMAGE_SIZE = SECTOR_SIZE * TOTAL_SECTORS


def build_pkdos_boot_sector() -> bytes:
    """Builds a valid 512-byte x86 boot sector with FAT12 BPB and PK-DOS 1983 banner."""
    bpb = bytearray(62)
    # Jump instruction: EB 3C 90
    bpb[0:3] = b"\xEB\x3C\x90"
    bpb[3:11] = b"PKDOS1.0"  # OEM Name
    struct.pack_into("<H", bpb, 11, SECTOR_SIZE)     # Bytes per sector (512)
    bpb[13] = 1                                      # Sectors per cluster (1)
    struct.pack_into("<H", bpb, 14, 1)               # Reserved sectors (1)
    bpb[16] = 2                                      # Number of FATs (2)
    struct.pack_into("<H", bpb, 17, 224)             # Root dir entries (224)
    struct.pack_into("<H", bpb, 19, TOTAL_SECTORS)   # Total sectors (2880)
    bpb[21] = 0xF0                                   # Media descriptor (1.44MB 3.5")
    struct.pack_into("<H", bpb, 22, 9)               # Sectors per FAT (9)
    struct.pack_into("<H", bpb, 24, 18)              # Sectors per track (18)
    struct.pack_into("<H", bpb, 26, 2)               # Number of heads (2)
    struct.pack_into("<I", bpb, 28, 0)               # Hidden sectors
    struct.pack_into("<I", bpb, 32, 0)               # Large sectors
    bpb[36] = 0x00                                   # Drive number
    bpb[37] = 0x00
    bpb[38] = 0x29                                   # Extended boot signature
    struct.pack_into("<I", bpb, 39, 0x19831028)      # Volume serial: 1983-10-28
    bpb[43:54] = b"MORSKOY1983"                      # Volume label (11 bytes)
    bpb[54:62] = b"FAT12   "                         # File system type (8 bytes)

    # 16-bit real-mode x86 bootloader code at offset 0x3E (prints banner via INT 10h)
    msg = (
        "\r\n"
        "====================================================================\r\n"
        " OKB IMPULS (1983) // ELEKTRONIKA-KR // OS PK-DOS v1.04\r\n"
        " MORSKOY BOY: RELATIVISTIC PERISCOPE SIMULATOR (d_tau = dt / gamma)\r\n"
        " EUGEN VALUEV SOVEREIGN RETRO ARCHIVE // FLOPPY EDITION 3.5\" 1.44MB\r\n"
        "====================================================================\r\n"
        " Files on disk A:\\ -> INDEX.HTM (CRT Periscope), MORSKOY.BAS, README.MD\r\n"
        " Press any key to reboot...\r\n\x00"
    ).encode("ascii")

    # Machine code at 0x7C3E:
    # cld; xor ax,ax; mov ds,ax; mov si, 0x7C00 + msg_offset
    # .loop: lodsb; test al,al; jz .wait; mov ah,0x0E; mov bx,0x000A; int 0x10; jmp .loop
    # .wait: xor ah,ah; int 0x16; int 0x19
    code = bytearray([
        0xFC,                   # cld
        0x31, 0xC0,             # xor ax, ax
        0x8E, 0xD8,             # mov ds, ax
        0xBE, 0x00, 0x00,       # mov si, imm16 (patched below)
        0xAC,                   # lodsb
        0x84, 0xC0,             # test al, al
        0x74, 0x09,             # jz +9 (.wait)
        0xB4, 0x0E,             # mov ah, 0x0E
        0xBB, 0x0A, 0x00,       # mov bx, 0x000A (green color)
        0xCD, 0x10,             # int 0x10
        0xEB, 0xF1,             # jmp .loop
        0x30, 0xE4,             # xor ah, ah
        0xCD, 0x16,             # int 0x16 (wait key)
        0xCD, 0x19,             # int 0x19 (warm reboot)
    ])
    msg_offset = 0x7C00 + len(bpb) + len(code)
    struct.pack_into("<H", code, 6, msg_offset)

    sector = bytearray(SECTOR_SIZE)
    sector[0:len(bpb)] = bpb
    sector[len(bpb):len(bpb) + len(code)] = code
    sector[len(bpb) + len(code):len(bpb) + len(code) + len(msg)] = msg
    sector[510] = 0x55
    sector[511] = 0xAA
    return bytes(sector)


def set_fat12_entry(fat: bytearray, cluster: int, value: int) -> None:
    offset = (cluster * 3) // 2
    if cluster % 2 == 0:
        fat[offset] = value & 0xFF
        fat[offset + 1] = (fat[offset + 1] & 0xF0) | ((value >> 8) & 0x0F)
    else:
        fat[offset] = (fat[offset] & 0x0F) | ((value << 4) & 0xF0)
        fat[offset + 1] = (value >> 4) & 0xFF


def make_dir_entry(name8: str, ext3: str, attr: int, start_cluster: int, size: int) -> bytes:
    entry = bytearray(32)
    entry[0:8] = name8.ljust(8)[:8].encode("ascii")
    entry[8:11] = ext3.ljust(3)[:3].encode("ascii")
    entry[11] = attr
    # Timestamp: 1983-10-28 12:00:00 (DOS epoch starts 1980)
    dos_time = (12 << 11) | (0 << 5) | 0
    dos_date = ((1983 - 1980) << 9) | (10 << 5) | 28
    struct.pack_into("<H", entry, 22, dos_time)
    struct.pack_into("<H", entry, 24, dos_date)
    struct.pack_into("<H", entry, 26, start_cluster)
    struct.pack_into("<I", entry, 28, size)
    return bytes(entry)


def build_floppy_image(base_dir: pathlib.Path, out_path: pathlib.Path) -> None:
    img = bytearray(IMAGE_SIZE)

    # Sector 0: Boot Sector
    img[0:SECTOR_SIZE] = build_pkdos_boot_sector()

    # FAT1 (sectors 1..9) and FAT2 (sectors 10..18)
    fat = bytearray(9 * SECTOR_SIZE)
    fat[0] = 0xF0
    fat[1] = 0xFF
    fat[2] = 0xFF

    # Root directory (sectors 19..32, 224 entries * 32 bytes = 14 sectors)
    root_dir = bytearray(14 * SECTOR_SIZE)
    # Volume Label Entry
    root_dir[0:32] = make_dir_entry("MORSKOY ", "83 ", 0x08, 0, 0)

    files_to_pack = [
        ("INDEX", "HTM", base_dir / "index.html"),
        ("MORSKOY", "BAS", base_dir / "MORSKOY.BAS"),
        ("README", "MD", base_dir / "README.md"),
    ]

    next_cluster = 2  # First data cluster in FAT12 (maps to sector 33)
    dir_idx = 1

    for name8, ext3, fpath in files_to_pack:
        data = fpath.read_bytes()
        size = len(data)
        num_sectors = max(1, (size + SECTOR_SIZE - 1) // SECTOR_SIZE)
        start_cluster = next_cluster

        for i in range(num_sectors):
            cur_cluster = start_cluster + i
            data_sector = 33 + (cur_cluster - 2)
            chunk = data[i * SECTOR_SIZE:(i + 1) * SECTOR_SIZE]
            img[data_sector * SECTOR_SIZE:data_sector * SECTOR_SIZE + len(chunk)] = chunk
            if i < num_sectors - 1:
                set_fat12_entry(fat, cur_cluster, cur_cluster + 1)
            else:
                set_fat12_entry(fat, cur_cluster, 0xFFF)

        next_cluster += num_sectors
        root_dir[dir_idx * 32:(dir_idx + 1) * 32] = make_dir_entry(
            name8, ext3, 0x20, start_cluster, size
        )
        dir_idx += 1

    # Write FAT1, FAT2, and Root Directory into image
    img[1 * SECTOR_SIZE:10 * SECTOR_SIZE] = fat
    img[10 * SECTOR_SIZE:19 * SECTOR_SIZE] = fat
    img[19 * SECTOR_SIZE:33 * SECTOR_SIZE] = root_dir

    out_path.write_bytes(img)
    print(f"[OK] Built 1.44 MB PK-DOS 1.04 floppy image: {out_path} ({len(img):,} bytes)")


if __name__ == "__main__":
    here = pathlib.Path(__file__).resolve().parent
    build_floppy_image(here, here / "MORSKOY_1983_PKDOS.img")
