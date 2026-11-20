"""Türkçe arama terimleri: kök kelimeden sık çekim biçimlerini üretir (ünlü uyumu, ünsüz yumuşaması).

OpenAlex Türkçe ekleri köke indirgemez; "hasat" araması "hasadı"nı bulmaz. Bu yüzden sık biçimler açıkça yazılır.
Yalnız son kelime çekimlenir ("toprak işleme" -> "toprak işlemesi", "toprak işlemenin" ...).
"""
VOWELS = "aeıioöuü"
HARD = "çfhkpsşt"
NO_SOFT = {"robot", "prototip", "test", "set", "kit", "bant", "drift", "sert", "ilaçlama"}
SOFT = {"p": "b", "ç": "c", "t": "d", "k": "ğ"}


def _last_vowel(w):
    for ch in reversed(w):
        if ch in VOWELS:
            return ch
    return "e"


def _I(w):
    return {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}[_last_vowel(w)]


def _A(w):
    return "a" if _last_vowel(w) in "aıou" else "e"


def _D(w):
    return "t" if w[-1] in HARD else "d"


def _soft(w):
    syll = sum(ch in VOWELS for ch in w)
    if syll > 1 and w[-1] in SOFT and w not in NO_SOFT and w[-2] in VOWELS:
        return w[:-1] + SOFT[w[-1]]
    return w


def forms(word):
    w = word.lower()
    if " " in w:
        head, last = w.rsplit(" ", 1)
        return [f"{head} {f}" for f in forms(last)]
    I, A, D = _I(w), _A(w), _D(w)
    # Sorgu adresi uzunluk sınırını aşmasın diye yalnız en sık biçimler: yalın, -de, -ler, -leri, -(s)i, -(n)in, -(s)inde
    out = [w, w + D + A, w + "l" + A + "r", w + "l" + A + "r" + ("ı" if A == "a" else "i")]
    if w[-1] in VOWELS:
        out += [w + "s" + I, w + "n" + I + "n", w + "s" + I + "nd" + A]
    else:
        s = _soft(w)
        out += [s + I, s + I + "n", s + I + "nd" + A]
    seen, res = set(), []
    for f in out:
        if f not in seen:
            seen.add(f)
            res.append(f)
    return res


def query(words):
    """Kelime listesinden OR sorgusu; çok kelimeli ifadeler tırnaklı."""
    terms = []
    for wd in words:
        for f in forms(wd):
            terms.append(f'"{f}"' if " " in f else f)
    return " OR ".join(terms)


if __name__ == "__main__":
    for w in ["hasat", "makine", "domates", "fındık", "toprak işleme", "robot", "üzüm", "çay", "budama"]:
        print(w, "->", forms(w))
