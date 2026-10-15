from aiogram.fsm.state import State, StatesGroup


class Wizard(StatesGroup):
    origin = State()
    destination = State()
    dates = State()
    passengers = State()
    summary = State()
    filters = State()
    results = State()


class SubEdit(StatesGroup):
    threshold = State()
