from .base import Message, BaseParser
from .txt_parser import TxtParser
from .csv_parser import CsvParser


def get_parser(fmt: str) -> BaseParser:
    """根据格式名返回对应解析器。"""
    parsers = {
        "txt": TxtParser,
        "csv": CsvParser,
    }
    if fmt not in parsers:
        raise ValueError(f"不支持的格式 '{fmt}'，可选：{list(parsers)}")
    return parsers[fmt]()


__all__ = ["Message", "BaseParser", "TxtParser", "CsvParser", "get_parser"]
