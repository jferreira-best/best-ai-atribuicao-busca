import re

def clean_text(s: str) -> str:
    if not s: return ""
    s = s.replace("\r", " ")
    s = re.sub(r"\n+", " ", s)
    s = re.sub(r"\s{2,}", " ", s)
    return s.strip()

def filename_from_source(src: str) -> str:
    if not src: return ""
    if src.startswith(("http", "https")):
        return src.split("/")[-1]
    return src.replace("\\", "/").split("/")[-1]

def deduplicate_list(items: list) -> list:
    """Remove duplicatas de uma lista mantendo a ordem original."""
    return list(dict.fromkeys(items))