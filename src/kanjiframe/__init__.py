"""kanjiframe — read and write Japanese mainframe data (EBCDIC kana/kanji, COBOL records)."""
from .codec import decode, decode_report, encode, encode_report, register

__version__ = "0.1.0"

register()  # b"...".decode("ibm930") / "...".encode("ibm939")

__all__ = ["decode", "decode_report", "encode", "encode_report", "register", "__version__"]
