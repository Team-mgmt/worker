# zxingcpp.pyi
"""Python bindings for zxing-cpp"""

from typing import Union, Optional, List, Tuple, Any, overload
import numpy as np
from PIL import Image as PILImage

class BarcodeFormat:
    """Enumeration of zxing supported barcode formats"""

    Aztec: BarcodeFormat
    Codabar: BarcodeFormat
    Code39: BarcodeFormat
    Code93: BarcodeFormat
    Code128: BarcodeFormat
    DataMatrix: BarcodeFormat
    EAN8: BarcodeFormat
    EAN13: BarcodeFormat
    ITF: BarcodeFormat
    MaxiCode: BarcodeFormat
    PDF417: BarcodeFormat
    QRCode: BarcodeFormat
    MicroQRCode: BarcodeFormat
    RMQRCode: BarcodeFormat
    DataBar: BarcodeFormat
    DataBarExpanded: BarcodeFormat
    DataBarLimited: BarcodeFormat
    DXFilmEdge: BarcodeFormat
    UPCA: BarcodeFormat
    UPCE: BarcodeFormat
    NONE: BarcodeFormat
    LinearCodes: BarcodeFormat
    MatrixCodes: BarcodeFormat

    @property
    def name(self) -> str: ...
    @property
    def value(self) -> int: ...
    def __int__(self) -> int: ...
    def __eq__(self, other: object) -> bool: ...
    def __ne__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...
    def __or__(self, other: BarcodeFormat) -> BarcodeFormats: ...
    def __and__(self, other: BarcodeFormat) -> BarcodeFormat: ...

class BarcodeFormats:
    def __init__(self, format: BarcodeFormat) -> None: ...
    def __repr__(self) -> str: ...
    def __str__(self) -> str: ...
    def __eq__(self, other: object) -> bool: ...
    def __or__(self, other: BarcodeFormat) -> BarcodeFormats: ...

class Binarizer:
    """Enumeration of binarizers used before decoding images"""

    BoolCast: Binarizer
    FixedThreshold: Binarizer
    GlobalHistogram: Binarizer
    LocalAverage: Binarizer

    @property
    def name(self) -> str: ...
    @property
    def value(self) -> int: ...
    def __int__(self) -> int: ...
    def __eq__(self, other: object) -> bool: ...
    def __ne__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...

class EanAddOnSymbol:
    """Enumeration of options for EAN-2/5 add-on symbols check"""

    Ignore: EanAddOnSymbol
    """Ignore any Add-On symbol during read/scan"""
    Read: EanAddOnSymbol
    """Read EAN-2/EAN-5 Add-On symbol if found"""
    Require: EanAddOnSymbol
    """Require EAN-2/EAN-5 Add-On symbol to be present"""

    @property
    def name(self) -> str: ...
    @property
    def value(self) -> int: ...
    def __int__(self) -> int: ...
    def __eq__(self, other: object) -> bool: ...
    def __ne__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...

class ContentType:
    """Enumeration of content types"""

    Text: ContentType
    Binary: ContentType
    Mixed: ContentType
    GS1: ContentType
    ISO15434: ContentType
    UnknownECI: ContentType

    @property
    def name(self) -> str: ...
    @property
    def value(self) -> int: ...
    def __int__(self) -> int: ...
    def __eq__(self, other: object) -> bool: ...
    def __ne__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...

class TextMode:
    """Text mode enumeration"""

    Plain: TextMode
    """bytes() transcoded to unicode based on ECI info or guessed charset"""
    ECI: TextMode
    """standard content following the ECI protocol"""
    HRI: TextMode
    """Human Readable Interpretation (dependent on the ContentType)"""
    Hex: TextMode
    """bytes() transcoded to ASCII string of HEX values"""
    Escaped: TextMode
    """Use the EscapeNonGraphical() function"""

    @property
    def name(self) -> str: ...
    @property
    def value(self) -> int: ...
    def __int__(self) -> int: ...
    def __eq__(self, other: object) -> bool: ...
    def __ne__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...

class ImageFormat:
    """Enumeration of image formats supported by read_barcodes"""

    Lum: ImageFormat
    LumA: ImageFormat
    RGB: ImageFormat
    BGR: ImageFormat
    RGBA: ImageFormat
    ARGB: ImageFormat
    BGRA: ImageFormat
    ABGR: ImageFormat

    @property
    def name(self) -> str: ...
    @property
    def value(self) -> int: ...
    def __int__(self) -> int: ...
    def __eq__(self, other: object) -> bool: ...
    def __ne__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...

class ErrorType:
    """Error type enumeration"""

    NONE: ErrorType
    """No error"""
    Format: ErrorType
    """Data format error"""
    Checksum: ErrorType
    """Checksum error"""
    Unsupported: ErrorType
    """Unsupported content error"""

    @property
    def name(self) -> str: ...
    @property
    def value(self) -> int: ...
    def __int__(self) -> int: ...
    def __eq__(self, other: object) -> bool: ...
    def __ne__(self, other: object) -> bool: ...
    def __hash__(self) -> int: ...

class Point:
    """Represents the coordinates of a point in an image"""
    @property
    def x(self) -> int: ...
    @property
    def y(self) -> int: ...

class Position:
    """The position of a decoded symbol"""
    @property
    def top_left(self) -> Point: ...
    @property
    def top_right(self) -> Point: ...
    @property
    def bottom_left(self) -> Point: ...
    @property
    def bottom_right(self) -> Point: ...
    def __str__(self) -> str: ...

class Error:
    """Barcode reading error"""
    @property
    def type(self) -> ErrorType: ...
    @property
    def message(self) -> str: ...
    def __str__(self) -> str: ...

class Barcode:
    """The Barcode class"""
    @property
    def valid(self) -> bool: ...
    @property
    def text(self) -> str: ...
    @property
    def bytes(self) -> bytes: ...
    @property
    def format(self) -> BarcodeFormat: ...
    @property
    def symbology_identifier(self) -> str: ...
    @property
    def ec_level(self) -> str: ...
    @property
    def content_type(self) -> ContentType: ...
    @property
    def position(self) -> Position: ...
    @property
    def orientation(self) -> int: ...
    @property
    def error(self) -> Optional[Error]: ...

    # Experimental API
    @overload
    def to_image(
        self,
        scale: int = ...,
        add_hrt: bool = ...,
        add_quiet_zones: bool = ...,
    ) -> Image: ...
    @overload
    def to_image(
        self,
        *,
        size_hint: int = ...,
        with_hrt: bool = ...,
        with_quiet_zones: bool = ...,
    ) -> Image: ...
    @overload
    def to_svg(
        self,
        scale: int = ...,
        add_hrt: bool = ...,
        add_quiet_zones: bool = ...,
    ) -> str: ...
    @overload
    def to_svg(
        self,
        *,
        size_hint: int = ...,
        with_hrt: bool = ...,
        with_quiet_zones: bool = ...,
    ) -> str: ...

Result = Barcode

class Image:
    """8-bit grayscale image buffer"""
    @property
    def __array_interface__(self) -> dict: ...
    @property
    def shape(self) -> Tuple[int, int]: ...
    def __buffer__(self, flags: int) -> memoryview: ...

Bitmap = Image

class ImageView:
    """Memory view with custom strides and ImageFormat (Experimental API)"""
    def __init__(
        self,
        buffer: Any,
        width: int,
        height: int,
        format: ImageFormat,
        row_stride: int = ...,
        pix_stride: int = ...,
    ) -> None: ...
    @property
    def format(self) -> ImageFormat: ...
    def __buffer__(self, flags: int) -> memoryview: ...

ImageInput = Union[np.ndarray, PILImage.Image, memoryview, ImageView, Any]

def barcode_format_from_str(str: str) -> BarcodeFormat: ...
def barcode_formats_from_str(str: str) -> BarcodeFormats: ...
def read_barcode(
    image: ImageInput,
    formats: Union[BarcodeFormat, BarcodeFormats, None] = ...,
    try_rotate: bool = ...,
    try_downscale: bool = ...,
    text_mode: TextMode = ...,
    binarizer: Binarizer = ...,
    is_pure: bool = ...,
    ean_add_on_symbol: EanAddOnSymbol = ...,
    return_errors: bool = ...,
) -> Optional[Barcode]: ...
def read_barcodes(
    image: ImageInput,
    formats: Union[BarcodeFormat, BarcodeFormats, None] = ...,
    try_rotate: bool = ...,
    try_downscale: bool = ...,
    text_mode: TextMode = ...,
    binarizer: Binarizer = ...,
    is_pure: bool = ...,
    ean_add_on_symbol: EanAddOnSymbol = ...,
    return_errors: bool = ...,
) -> List[Barcode]: ...
def write_barcode(
    format: BarcodeFormat,
    text: Union[str, bytes],
    width: int = ...,
    height: int = ...,
    quiet_zone: int = ...,
    ec_level: int = ...,
) -> Image: ...

# Experimental API
def create_barcode(
    content: Union[str, bytes],
    format: BarcodeFormat,
    ec_level: str = ...,
) -> Barcode: ...
@overload
def write_barcode_to_image(
    barcode: Barcode,
    scale: int = ...,
    add_hrt: bool = ...,
    add_quiet_zones: bool = ...,
) -> Image: ...
@overload
def write_barcode_to_image(
    barcode: Barcode,
    *,
    size_hint: int = ...,
    with_hrt: bool = ...,
    with_quiet_zones: bool = ...,
) -> Image: ...
@overload
def write_barcode_to_svg(
    barcode: Barcode,
    scale: int = ...,
    add_hrt: bool = ...,
    add_quiet_zones: bool = ...,
) -> str: ...
@overload
def write_barcode_to_svg(
    barcode: Barcode,
    *,
    size_hint: int = ...,
    with_hrt: bool = ...,
    with_quiet_zones: bool = ...,
) -> str: ...
