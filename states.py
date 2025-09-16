from aiogram.fsm.state import StatesGroup, State

class NewComplaint(StatesGroup):
    text = State()
    category = State()
    address = State()      # текстовый адрес (можно пустым)
    location = State()     # геопозиция (можно пропустить)
    media = State()        # фото/видео (можно пропустить)
    confirm = State()
