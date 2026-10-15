from sources.base import Source

_REGISTRY: dict[str, type[Source]] = {}


def register(cls: type[Source]) -> type[Source]:
    if cls.name in _REGISTRY:
        raise ValueError(f"Источник {cls.name} уже зарегистрирован")
    _REGISTRY[cls.name] = cls
    return cls


def all_sources() -> dict[str, type[Source]]:
    _load_builtin()
    return dict(_REGISTRY)


def get_source(name: str) -> Source:
    _load_builtin()
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise KeyError(f"Неизвестный источник: {name}. Доступны: {', '.join(sorted(_REGISTRY))}") from None


def _load_builtin() -> None:
    # Импорт модулей регистрирует источники через @register
    import sources.aviakassa  # noqa: F401
    import sources.aviasales_api  # noqa: F401
    import sources.egyptticket  # noqa: F401
    import sources.kupibilet  # noqa: F401
    import sources.onetwotrip  # noqa: F401
    import sources.ticket_egypt  # noqa: F401
    import sources.tutu  # noqa: F401
