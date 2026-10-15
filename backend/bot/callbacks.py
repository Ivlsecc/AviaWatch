"""Callback-данные inline-кнопок (≤ 64 байт после упаковки)."""

from aiogram.filters.callback_data import CallbackData


class Menu(CallbackData, prefix="m"):
    action: str  # home | search | subs | filters | help


class Wiz(CallbackData, prefix="w"):
    action: str  # next | back | reset | cancel | search | direct | filters
    step: str = ""


class PlacePick(CallbackData, prefix="p"):
    step: str  # from | to
    idx: int


class Cal(CallbackData, prefix="c"):
    action: str  # day | nav | single | noop
    y: int = 0
    m: int = 0
    d: int = 0


class Pax(CallbackData, prefix="x"):
    kind: str  # adults | children | infants
    delta: int


class Flt(CallbackData, prefix="f"):
    field: str
    ctx: str  # wiz | menu


class Res(CallbackData, prefix="r"):
    action: str  # page | subscribe | refresh
    page: int = 0


class Sub(CallbackData, prefix="s"):
    action: str
    id: int = 0


class Flex(CallbackData, prefix="g"):
    """Перейти на более дешёвую дату из подсказки гибких дат."""

    y: int
    m: int
    d: int
