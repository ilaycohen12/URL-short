ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
BASE = len(ALPHABET)


def encode(num: int) -> str:
    if num == 0:
        return ALPHABET[0]
    digits = []
    while num > 0:
        num, remainder = divmod(num, BASE)
        digits.append(ALPHABET[remainder])
    return "".join(reversed(digits))


def decode(code: str) -> int:
    num = 0
    for char in code:
        try:
            num = num * BASE + ALPHABET.index(char)
        except ValueError:
            raise ValueError(f"invalid short code: {code!r}") from None
    return num
