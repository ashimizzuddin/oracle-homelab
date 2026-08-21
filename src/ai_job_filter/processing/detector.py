import re

ID_KEYWORDS = [
    r"loker",
    r"lowongan",
    r"dibutuhkan",
    r"dicari",
    r"kualifikasi",
    r"gaji",
    r"lamaran",
    r"rekrutmen",
    r"magang",
    r"internship",
]
EN_KEYWORDS = [
    r"hiring",
    r"job",
    r"vacancy",
    r"developer",
    r"engineer",
    r"salary",
    r"apply",
    r"position",
    r"opportunity",
    r"remote",
]

PATTERN = re.compile("|".join(ID_KEYWORDS + EN_KEYWORDS), re.IGNORECASE)


def is_potential_job(text: str | None, has_media: bool) -> bool:
    """
    Determine if a message should enter the processing pipeline.
    If it has media, it is NEVER rejected here (Correction 3).
    If it's text-only, it must contain a job keyword.
    """
    if has_media:
        return True

    if not text:
        return False

    return bool(PATTERN.search(text))
