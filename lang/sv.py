# Swedish filler words for FreeWispr-SV

SWEDISH_FILLERS = [
    # Swedish fillers
    "eh", "em", "öh", "öhm", "äh", "ahm",
    "liksom", "typ", "ba", "bara", "alltså",
    "liknande", "sådär", "någon", "nåt",
    "kanske", "ju", "nog", "väl", "då",
    "ja", "nej", "aa", "mm", "mhm", "aha",
    # Common Swedish speech patterns
    "såhär", "öhre", "tjo", "hej",
]

# Regex pattern for Swedish filler removal
import re

def get_swedish_filler_pattern():
    """Returns compiled regex for Swedish filler words."""
    return re.compile(
        r'\b(' + '|'.join(re.escape(f) for f in SWEDISH_FILLERS) + r')\b[,.]?',
        re.IGNORECASE | re.UNICODE,
    )
