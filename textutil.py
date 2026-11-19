"""Нормализация текста и перевод русских числительных в цифры (Vosk выдаёт «тридцать», а не «30»)."""
import re

UNITS = {
    "ноль": 0, "один": 1, "одна": 1, "одну": 1, "одного": 1, "два": 2, "две": 2, "двух": 2,
    "три": 3, "трёх": 3, "трех": 3, "четыре": 4, "четырёх": 4, "четырех": 4, "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6, "семь": 7, "семи": 7, "восемь": 8, "восьми": 8, "девять": 9, "девяти": 9,
}
TEENS = {
    "десять": 10, "десяти": 10, "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "пятнадцати": 15, "шестнадцать": 16, "семнадцать": 17,
    "восемнадцать": 18, "девятнадцать": 19,
}
TENS = {
    "двадцать": 20, "двадцати": 20, "тридцать": 30, "тридцати": 30, "сорок": 40, "сорока": 40,
    "пятьдесят": 50, "пятидесяти": 50, "шестьдесят": 60, "семьдесят": 70, "восемьдесят": 80,
    "девяносто": 90,
}
HUNDREDS = {
    "сто": 100, "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
}


def _num(tok):
    if tok in HUNDREDS:
        return HUNDREDS[tok], 3
    if tok in TENS:
        return TENS[tok], 2
    if tok in TEENS:
        return TEENS[tok], 1.5
    if tok in UNITS:
        return UNITS[tok], 1
    return None, None


def words_to_digits(text):
    out, cur, last = [], None, None
    for tok in text.split():
        v, rank = _num(tok)
        if v is None:
            if cur is not None:
                out.append(str(cur)); cur = None
            out.append(tok)
            continue
        if cur is not None and rank < last and last >= 2 and not (rank == 1.5 and last == 2):
            cur += v
        else:
            if cur is not None:
                out.append(str(cur))
            cur = v
        last = rank
    if cur is not None:
        out.append(str(cur))
    return " ".join(out)


def normalize(text):
    t = text.lower().replace("ё", "е")
    t = re.sub(r"[^\w\s:+\-./]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return words_to_digits(t)


_TR = dict(zip("абвгдезийклмнопрстуфхцы", "abvgdeziyklmnoprstufhcy"))
_TR.update({"ж": "zh", "ч": "ch", "ш": "sh", "щ": "sch", "ю": "yu", "я": "ya", "э": "e", "ь": "", "ъ": "", "е": "e"})


def translit(text):
    return "".join(_TR.get(c, c) for c in text.lower())


GREEK = {"alpha": "альфа", "beta": "бета", "gamma": "гамма", "delta": "дельта", "Delta": "дельта",
         "epsilon": "эпсилон", "varepsilon": "эпсилон", "theta": "тэта", "lambda": "лямбда", "mu": "мю",
         "pi": "пи", "rho": "ро", "sigma": "сигма", "Sigma": "сигма", "tau": "тау", "phi": "фи", "varphi": "фи",
         "omega": "омега", "Omega": "омега", "nu": "ню", "xi": "кси", "eta": "эта", "chi": "хи", "psi": "пси"}
FUNCS = {"sin": "синус", "cos": "косинус", "tg": "тангенс", "tan": "тангенс", "ctg": "котангенс", "cot": "котангенс",
         "arcsin": "арксинус", "arccos": "арккосинус", "arctg": "арктангенс", "arctan": "арктангенс",
         "ln": "натуральный логарифм", "lg": "десятичный логарифм", "exp": "экспонента", "max": "максимум",
         "min": "минимум"}
SYMS = [(r"\\pm", " плюс минус "), (r"\\mp", " минус плюс "), (r"\\cdot", " умножить на "),
        (r"\\times", " умножить на "), (r"\\div", " делить на "), (r"\\leq?\b", " меньше или равно "),
        (r"\\geq?\b", " больше или равно "), (r"\\neq?\b", " не равно "), (r"\\approx", " примерно равно "),
        (r"\\infty", " бесконечность "), (r"\\to\b", " стремится к "), (r"\\Rightarrow", " следовательно "),
        (r"\\iff", " тогда и только тогда "), (r"\\in\b", " принадлежит "), (r"\\cup", " объединение "),
        (r"\\cap", " пересечение "), (r"\\int", " интеграл "), (r"\\sum", " сумма "), (r"\\lim", " предел "),
        (r"\\log", " логарифм "), (r"\\angle", " угол "), (r"\\perp", " перпендикулярно "),
        (r"\\parallel", " параллельно "), (r"\\circ", " градусов "), (r"\\%", " процентов "),
        (r"\\degree", " градусов "), (r"\\vec", " вектор "), (r"\\overline", " "), (r"\\mathbb\{R\}", " эр ")]


def _frac(m):
    a, b = m.group(1).strip(), m.group(2).strip()
    simple = lambda x: re.fullmatch(r"[\w.,]+", x) is not None
    if simple(a) and simple(b):
        return f" {a} делить на {b} "
    return f" дробь: в числителе {a}, в знаменателе {b}, "


def latex_to_speech(m):
    """Формула LaTeX -> как её прочитать вслух по-русски."""
    t = m
    t = re.sub(r"\\(left|right|big|Big|bigg|displaystyle|limits|mathrm|text|operatorname)\b", " ", t)
    t = re.sub(r"\\[,;:! ]|~", " ", t)
    for _ in range(6):   # вложенные дроби и корни — изнутри наружу
        t2 = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", _frac, t)
        t2 = re.sub(r"\\sqrt\[([^\]]*)\]\{([^{}]*)\}", r" корень степени \1 из (\2) ", t2)
        t2 = re.sub(r"\\sqrt\{([^{}]*)\}", r" корень из (\1) ", t2)
        t2 = re.sub(r"\\sqrt\s*(\w)", r" корень из \1 ", t2)
        if t2 == t:
            break
        t = t2
    t = re.sub(r"\\(int|sum|prod)_\{?([^{}^]+?)\}?\^\{?([^{}\s]+?)\}?(?=\s|\\|\w)",
               lambda x: {"int": " интеграл", "sum": " сумма", "prod": " произведение"}[x.group(1)]
               + f" от {x.group(2)} до {x.group(3)} ", t)
    t = re.sub(r"\^\{?2\}?(?![\d])", " в квадрате ", t)
    t = re.sub(r"\^\{?3\}?(?![\d])", " в кубе ", t)
    t = re.sub(r"\^\{\\circ\}|\^\\circ", " градусов ", t)
    t = re.sub(r"\^\{([^{}]*)\}", r" в степени \1 ", t)
    t = re.sub(r"\^(-?\w)", r" в степени \1 ", t)
    t = re.sub(r"_\{([^{}]*)\}", r" \1 ", t)
    t = re.sub(r"_(\w)", r" \1 ", t)
    for pat, rep in SYMS:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\\(" + "|".join(sorted(FUNCS, key=len, reverse=True)) + r")\b", lambda x: " " + FUNCS[x.group(1)] + " ", t)
    t = re.sub(r"\\(" + "|".join(GREEK) + r")\b", lambda x: " " + GREEK[x.group(1)] + " ", t)
    t = re.sub(r"\\[a-zA-Z]+", " ", t)
    t = t.replace("'", " штрих ")
    t = t.replace("-", " минус ")
    t = t.replace("+", " плюс ").replace("=", " равно ").replace("<", " меньше ").replace(">", " больше ")
    t = t.replace("*", " умножить на ").replace("/", " делить на ").replace("|", " модуль ")
    t = re.sub(r"\(\s*([\w.,]+)\s*\)", r" \1 ", t)   # скобки вокруг одного числа/буквы не читаем
    t = re.sub(r"[{}()\[\]]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def for_speech(text):
    """Текст для озвучки: формулы словами, без markdown, кода и ссылок."""
    t = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    t = re.sub(r"```.*?(```|$)", " (код показан на экране) ", t, flags=re.S)
    t = re.sub(r"\$\$(.+?)\$\$", lambda m: " " + latex_to_speech(m.group(1)) + ". ", t, flags=re.S)
    t = re.sub(r"\\\[(.+?)\\\]", lambda m: " " + latex_to_speech(m.group(1)) + ". ", t, flags=re.S)
    t = re.sub(r"\$(.+?)\$", lambda m: " " + latex_to_speech(m.group(1)) + " ", t)
    t = re.sub(r"\\\((.+?)\\\)", lambda m: " " + latex_to_speech(m.group(1)) + " ", t)
    t = re.sub(r"https?://\S+", "ссылка", t)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"^\s*#+\s*", "", t, flags=re.M)
    t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)
    t = re.sub(r"[*_#>|]", "", t)
    return re.sub(r"[ \t]+", " ", t).strip()
