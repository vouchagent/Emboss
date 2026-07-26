"""Image embedding: JPEG and PNG loading without PIL/Pillow.

Headers are parsed manually with struct; JPEG bytes pass through as
DCTDecode, PNG pixels are decompressed and re-encoded for FlateDecode.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Union

from .pdf.objects import PdfArray, PdfDict, PdfName, PdfRef, PdfStream

__all__ = ["ImageData", "load_image", "image_xobject"]


@dataclass
class ImageData:
    """Parsed image ready for PDF embedding."""

    width: int
    height: int
    color_space: str
    bits_per_component: int
    data: bytes
    filter: str
    has_alpha: bool = False
    alpha_data: bytes | None = None


def load_image(source: Union[str, bytes, Path]) -> ImageData:
    """Load an image from a file path or raw bytes.

    Auto-detects JPEG vs PNG from the magic bytes.
    """
    if isinstance(source, (str, Path)):
        raw = Path(source).read_bytes()
    else:
        raw = source

    if raw[:2] == b"\xff\xd8":
        return _parse_jpeg(raw)
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return _parse_png(raw)
    raise ValueError("unsupported image format (expected JPEG or PNG)")


# ---------------------------------------------------------------------------
# JPEG
# ---------------------------------------------------------------------------

def _parse_jpeg(data: bytes) -> ImageData:
    """Parse JPEG header for dimensions and component count.

    The entire file is kept as-is for DCTDecode — the PDF reader does
    the decompression.
    """
    i = 2
    while i < len(data) - 1:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        i += 2
        if marker in (0xC0, 0xC1, 0xC2):
            bits = data[i + 2]
            height = struct.unpack(">H", data[i + 3 : i + 5])[0]
            width = struct.unpack(">H", data[i + 5 : i + 7])[0]
            components = data[i + 7]
            color_space = {1: "DeviceGray", 3: "DeviceRGB", 4: "DeviceCMYK"}.get(
                components, "DeviceRGB"
            )
            return ImageData(
                width=width,
                height=height,
                color_space=color_space,
                bits_per_component=bits,
                data=data,
                filter="DCTDecode",
            )
        if marker in (0xD0, 0xD1, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7,
                       0xD8, 0xD9, 0x01, 0x00):
            continue
        if i + 2 <= len(data):
            length = struct.unpack(">H", data[i : i + 2])[0]
            i += length
        else:
            break
    raise ValueError("could not find SOF marker in JPEG")


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------

def _parse_png(data: bytes) -> ImageData:
    """Parse PNG chunks: read IHDR, collect IDAT, un-filter scanlines."""
    pos = 8
    width = height = bit_depth = color_type = 0
    idat_chunks: list[bytes] = []
    palette: bytes = b""

    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunk_type = data[pos + 4 : pos + 8]
        chunk_data = data[pos + 8 : pos + 8 + length]
        pos += 12 + length  # 4 len + 4 type + data + 4 crc

        if chunk_type == b"IHDR":
            (width, height, bit_depth, color_type) = struct.unpack(
                ">IIBB", chunk_data[:10]
            )
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)
        elif chunk_type == b"PLTE":
            palette = chunk_data
        elif chunk_type == b"IEND":
            break

    if width == 0:
        raise ValueError("PNG missing IHDR chunk")

    raw = zlib.decompress(b"".join(idat_chunks))

    # color_type: 0 = gray, 2 = RGB, 3 = indexed, 4 = gray+alpha, 6 = RGBA
    if color_type == 0:
        channels = 1
        color_space = "DeviceGray"
    elif color_type == 2:
        channels = 3
        color_space = "DeviceRGB"
    elif color_type == 3:
        channels = 1
        color_space = "Indexed"
    elif color_type == 4:
        channels = 2
        color_space = "DeviceGray"
    elif color_type == 6:
        channels = 4
        color_space = "DeviceRGB"
    else:
        raise ValueError(f"unsupported PNG color type {color_type}")

    pixel_bytes = channels * (bit_depth // 8 or 1)
    stride = width * pixel_bytes
    scanlines = _unfilter(raw, stride, height, pixel_bytes)

    has_alpha = color_type in (4, 6)
    alpha_data = None

    if color_type == 3:
        # Indexed → expand via palette to RGB
        rgb = bytearray()
        for y in range(height):
            row_start = y * width
            for x in range(width):
                idx = scanlines[row_start + x]
                rgb.extend(palette[idx * 3 : idx * 3 + 3])
        pixel_data = zlib.compress(bytes(rgb), 6)
        color_space = "DeviceRGB"
        return ImageData(
            width=width,
            height=height,
            color_space=color_space,
            bits_per_component=8,
            data=pixel_data,
            filter="FlateDecode",
        )

    if has_alpha:
        if color_type == 6:
            color_channels = 3
        else:
            color_channels = 1
        rgb = bytearray()
        alpha = bytearray()
        bpc = bit_depth // 8 or 1
        for y in range(height):
            row_start = y * stride
            for x in range(width):
                px_start = row_start + x * channels * bpc
                for c in range(color_channels):
                    rgb.extend(scanlines[px_start + c * bpc : px_start + (c + 1) * bpc])
                alpha.extend(
                    scanlines[px_start + color_channels * bpc : px_start + (color_channels + 1) * bpc]
                )
        pixel_data = zlib.compress(bytes(rgb), 6)
        alpha_data = zlib.compress(bytes(alpha), 6)
    else:
        pixel_data = zlib.compress(bytes(scanlines), 6)

    return ImageData(
        width=width,
        height=height,
        color_space=color_space,
        bits_per_component=bit_depth,
        data=pixel_data,
        filter="FlateDecode",
        has_alpha=has_alpha,
        alpha_data=alpha_data,
    )


def _unfilter(raw: bytes, stride: int, height: int, bpp: int) -> bytearray:
    """Undo PNG per-row filtering (None, Sub, Up, Average, Paeth)."""
    result = bytearray()
    prev_row = bytearray(stride)
    pos = 0

    for _ in range(height):
        if pos >= len(raw):
            break
        filter_type = raw[pos]
        pos += 1
        row = bytearray(raw[pos : pos + stride])
        pos += stride

        if filter_type == 1:  # Sub
            for i in range(bpp, stride):
                row[i] = (row[i] + row[i - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                row[i] = (row[i] + prev_row[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + (a + prev_row[i]) // 2) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev_row[i]
                c = prev_row[i - bpp] if i >= bpp else 0
                row[i] = (row[i] + _paeth_predictor(a, b, c)) & 0xFF

        result.extend(row)
        prev_row = row

    return result


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


# ---------------------------------------------------------------------------
# PDF XObject
# ---------------------------------------------------------------------------

def image_xobject(assembler, image: ImageData) -> PdfRef:
    """Create the PDF XObject for an image and return its reference."""
    smask_ref = None
    if image.has_alpha and image.alpha_data is not None:
        smask_stream = PdfStream(data=image.alpha_data, compress=False)
        smask_stream.dictionary["Type"] = PdfName("XObject")
        smask_stream.dictionary["Subtype"] = PdfName("Image")
        smask_stream.dictionary["Width"] = image.width
        smask_stream.dictionary["Height"] = image.height
        smask_stream.dictionary["ColorSpace"] = PdfName("DeviceGray")
        smask_stream.dictionary["BitsPerComponent"] = image.bits_per_component
        smask_stream.dictionary["Filter"] = PdfName("FlateDecode")
        smask_ref = assembler.add(smask_stream)

    if image.filter == "DCTDecode":
        img_stream = PdfStream(data=image.data, compress=False)
        img_stream.dictionary["Filter"] = PdfName("DCTDecode")
    else:
        img_stream = PdfStream(data=image.data, compress=False)
        img_stream.dictionary["Filter"] = PdfName("FlateDecode")

    img_stream.dictionary["Type"] = PdfName("XObject")
    img_stream.dictionary["Subtype"] = PdfName("Image")
    img_stream.dictionary["Width"] = image.width
    img_stream.dictionary["Height"] = image.height
    img_stream.dictionary["ColorSpace"] = PdfName(image.color_space)
    img_stream.dictionary["BitsPerComponent"] = image.bits_per_component

    if smask_ref is not None:
        img_stream.dictionary["SMask"] = smask_ref

    return assembler.add(img_stream)
