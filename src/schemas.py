from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from models import UserRole, OperationType, str_256

class OrmBaseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

# --- User Schemas ---
# Схема для создания пользователя (входные данные)
# UsersAddDTO у вас уже есть, я её немного расширю для примера других полей
class UserCreateSchema(BaseModel):
    tg_id: int
    username: Optional[str_256] = None # str_256 если хотите валидацию длины
    role: UserRole
    is_active: Optional[bool] = True
    # admin_password: Optional[str] = None # Если нужна проверка пароля админа при регистрации

# Схема для обновления пользователя (входные данные, все поля опциональны)
class UserUpdateSchema(BaseModel):
    username: Optional[str_256] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    # last_login можно обновлять системно, не через API пользователем

# Схема для чтения данных пользователя (выходные данные)
# UsersDTO у вас уже есть, она похожа на эту
class UserReadSchema(OrmBaseModel):
    id: int
    tg_id: int
    username: Optional[str_256] = None
    last_login: datetime # В модели это updated_at, но семантически last_login
    role: UserRole
    is_active: Optional[bool] = None # В модели bool | None
    created_at: datetime
    # operations: List["OperationReadSchema"] = [] # Для вложенного ответа, если нужно

# --- Item Schemas ---
# Схема для создания товара
class ItemCreateSchema(BaseModel):
    code: str_256 # Аналог barcode
    name: str_256
    weight: int
    quantity: int
    location_id: int
    description: Optional[str_256] = None # В модели это str_256, но может быть и опциональным

# Схема для обновления товара
class ItemUpdateSchema(BaseModel):
    code: Optional[str_256] = None
    name: Optional[str_256] = None
    weight: Optional[int] = None
    quantity: Optional[int] = None
    location_id: Optional[int] = None
    description: Optional[str_256] = None

# Схема для чтения товара
class ItemReadSchema(OrmBaseModel):
    id: int
    code: str_256
    name: str_256
    weight: int
    quantity: int
    location_id: int
    description: str_256 # В модели это не Optional
    created_at: datetime
    # location: Optional["LocationReadSchema"] = None # Для вложенного ответа
    # operations: List["OperationReadSchema"] = [] # Для вложенного ответа

# --- Location Schemas ---
# Схема для создания локации
class LocationCreateSchema(BaseModel):
    name: str_256
    description: Optional[str_256] = None # В модели это str_256, но может быть и опциональным

# Схема для обновления локации
class LocationUpdateSchema(BaseModel):
    name: Optional[str_256] = None
    description: Optional[str_256] = None

# Схема для чтения локации
class LocationReadSchema(OrmBaseModel):
    id: int
    name: str_256
    description: str_256 # В модели это не Optional
    created_at: datetime
    # items: List["ItemReadSchema"] = [] # Для вложенного ответа

# --- Operation Schemas ---
# Схема для создания операции
class OperationCreateSchema(BaseModel):
    item_id: int
    user_id: int # ID пользователя, совершающего операцию
    type: OperationType
    note: Optional[str_256] = None # В модели это str_256, но может быть и опциональным
    created_by_id: int # Поле из вашей модели OperationORM

# Схема для обновления операции (обычно операции не обновляются, а создаются новые, но для полноты)
class OperationUpdateSchema(BaseModel):
    type: Optional[OperationType] = None
    note: Optional[str_256] = None
    # item_id, user_id, created_by_id обычно не меняются

# Схема для чтения операции
class OperationReadSchema(OrmBaseModel):
    id: int
    item_id: int
    user_id: int
    type: OperationType
    note: str_256 # В модели это не Optional
    created_at: datetime
    created_by_id: int
    # item: Optional["ItemReadSchema"] = None # Для вложенного ответа
    # user: Optional["UserReadSchema"] = None # Для вложенного ответа
class DeleteResponseSchema(BaseModel):
    message: str
    id: Optional[int] = None # ID удаленного объекта, если нужно его вернуть
    status: str = "success"