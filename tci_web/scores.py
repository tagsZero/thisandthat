from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

SCALES = (
    ("NS", "자극추구", "기질"), ("HA", "위험회피", "기질"),
    ("RD", "사회적 민감성", "기질"), ("PS", "인내력", "기질"),
    ("SD", "자율성", "성격"), ("CO", "연대감", "성격"),
    ("ST", "자기초월", "성격"),
)
# Adult TCI-RS labels. The source's P/C codes use the app's PS/CO prefixes.
SUBSCALES = {
    "NS": (("NS1", "탐색적 흥분"), ("NS2", "충동성"), ("NS3", "무절제"), ("NS4", "자유분방")),
    "HA": (("HA1", "예기불안"), ("HA2", "불확실성에 대한 두려움"), ("HA3", "낯선 사람에 대한 수줍음"), ("HA4", "쉽게 지침")),
    "RD": (("RD1", "정서적 감수성"), ("RD2", "정서적 개방성"), ("RD3", "친밀감"), ("RD4", "의존")),
    "PS": (("PS1", "근면"), ("PS2", "끈기"), ("PS3", "성취에 대한 야망"), ("PS4", "완벽주의")),
    "SD": (("SD1", "책임감"), ("SD2", "목적의식"), ("SD3", "유능감"), ("SD4", "자기수용"), ("SD5", "자기일치")),
    "CO": (("CO1", "타인수용"), ("CO2", "공감"), ("CO3", "이타성"), ("CO4", "관대함"), ("CO5", "공평")),
    "ST": (("ST1", "창조적 자기망각"), ("ST2", "우주만물과의 일체감"), ("ST3", "영성 수용")),
}
DEFAULT_SETTINGS = {"low": "45", "high": "56", "rounding": "none"}


def parse_settings(form, current=None):
    """Keep the legacy keys; only enabled scale overrides are persisted."""
    settings = {**DEFAULT_SETTINGS, **(current or {})}
    errors = {}
    for key in ("low", "high", "rounding"):
        settings[key] = form.get(key, str(settings[key])).strip()
    preset = form.get("preset", "custom")
    if preset in ("t55", "t56"):
        settings.update(low="45", high=preset[1:])
    elif preset != "custom":
        errors["preset"] = "분류 기준을 확인해 주세요."

    def boundaries(values, prefix=""):
        numbers = {}
        for key in ("low", "high"):
            try:
                numbers[key] = Decimal(values[key])
                if not numbers[key].is_finite():
                    raise InvalidOperation
            except InvalidOperation:
                errors[prefix + key] = "유한한 십진수 경계를 입력해 주세요."
        if len(numbers) == 2 and not any(prefix + key in errors for key in ("low", "high")):
            if numbers["high"] <= numbers["low"]:
                errors[prefix + "high"] = "높음 시작값은 낮음 종료값보다 커야 합니다."

    boundaries(settings)
    if settings["rounding"] not in ("none", "one_decimal", "integer"):
        errors["rounding"] = "반올림 방식을 확인해 주세요."
    settings["overrides"] = {}
    for code, _, _ in SCALES:
        if form.get(f"{code}_override") == "1":
            values = {key: form.get(f"{code}_{key}", "").strip() for key in ("low", "high")}
            settings["overrides"][code] = values
            boundaries(values, f"{code}_")
    return settings, errors


def classification_value(value, rounding):
    number = Decimal(str(value))
    if rounding in ("integer", "one_decimal"):
        unit = Decimal("1") if rounding == "integer" else Decimal("0.1")
        # Already integral at this precision, including large scientific notation.
        if number.as_tuple().exponent < unit.as_tuple().exponent:
            with localcontext() as context:
                context.prec = max(28, len(number.as_tuple().digits) + 1)
                number = number.quantize(unit, rounding=ROUND_HALF_UP)
    return number


def parse_scores(form, current=None):
    """Merge submitted fields; an absent field preserves its saved value.

    Empty strings explicitly clear values. Work on a copy so failed validation
    and previews cannot mutate a loaded report's scores.
    """
    scores, errors = deepcopy(current or {}), {}

    def parse_fields(target, code, fields):
        for field in fields:
            key = f"{code}_{field}"
            if key not in form:
                target.setdefault(field, None)
                continue
            value = form[key].strip()
            target[field] = value or None
            if not value:
                continue
            try:
                number = Decimal(value)
                if not number.is_finite():
                    raise InvalidOperation
                if field == "raw" and (number < 0 or number != number.to_integral_value()):
                    raise InvalidOperation
                if field == "percentile" and not 0 <= number <= 100:
                    raise InvalidOperation
            except InvalidOperation:
                errors[key] = {
                    "raw": "0 이상의 정수를 입력해 주세요.",
                    "t": "유효한 T점수를 입력해 주세요.",
                    "percentile": "0~100 사이의 수치를 입력해 주세요.",
                }[field]

    for code, _, _ in SCALES:
        parse_fields(scores.setdefault(code, {}), code, ("raw", "t", "percentile"))
    parse_fields(scores.setdefault("SC", {}), "SC", ("raw", "t", "percentile"))
    subscales = scores.setdefault("subscales", {})
    for items in SUBSCALES.values():
        for code, _ in items:
            parse_fields(subscales.setdefault(code, {}), code, ("raw",))
    return scores, errors


def report_types(scores, settings):
    grades, applied, changed = {}, {}, {}
    for code, _, _ in SCALES:
        value = scores.get(code, {}).get("t")
        if value is None or value == "":
            grades[code] = None
            applied[code] = None
            changed[code] = False
            continue
        number = classification_value(value, settings.get("rounding", "none"))
        applied[code] = str(number)
        changed[code] = number != Decimal(str(value))
        bounds = settings.get("overrides", {}).get(code, settings)
        grades[code] = "L" if number <= Decimal(bounds["low"]) else (
            "H" if number >= Decimal(bounds["high"]) else "M"
        )
    def combine(codes):
        return "".join(grades[c] for c in codes) if all(grades[c] for c in codes) else None
    return {"temperament": combine(("NS", "HA", "RD")),
            "character": combine(("SD", "CO", "ST")), "grades": grades,
            "applied": applied, "changed": changed}


def profile_rows(scores, types):
    """웹 보고서와 작성 화면이 공유하는 입력 백분위 위치. T로 환산하지 않는다."""
    rows = []
    for code, name, family in SCALES:
        score = scores.get(code, {})
        percentile = score.get('percentile')
        position = None
        if percentile not in (None, ''):
            number = Decimal(str(percentile))
            if not number.is_finite() or not 0 <= number <= 100:
                raise ValueError('저장된 백분위를 확인해 주세요.')
            position = format(number, 'f')
        rows.append(dict(code=code, name=name, family=family, score=score,
                         grade=types['grades'][code], applied=types['applied'][code],
                         rounded=types['changed'][code], position=position))
    return rows
