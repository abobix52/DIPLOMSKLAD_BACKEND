import asyncio
import os
from contextlib import asynccontextmanager
from typing import Annotated, Optional, List, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

# Импортируем из вашего НОВОГО проекта
from database import async_session_factory, async_engine, Base
from models import UserORM, OperationORM, ItemORM, LocationORM, UserRole, OperationType
from schemas import (
    UserCreateSchema, UserReadSchema, UserUpdateSchema,
    ItemCreateSchema, ItemReadSchema, ItemUpdateSchema,
    OperationCreateSchema, OperationReadSchema, # Эти схемы будут адаптированы ниже
    LocationCreateSchema, LocationReadSchema, LocationUpdateSchema,
    DeleteResponseSchema,
)
import requests as rq

# Добавляем необходимые схемы, адаптированные под вашу models.py
# Нужно, чтобы OperationCreateSchema и OperationReadSchema были доступны
# с учетом того, что quantity, from_location_id, to_location_id не хранятся в OperationORM

from pydantic import BaseModel, Field, conint # Для OperationCreateSchema

# Переопределяем OperationCreateSchema для входных данных
class AdaptedOperationCreateSchema(BaseModel):
    item_id: int
    # user_id тут - это tg_id пользователя, который совершает операцию,
    # в OperationORM user_id - это ID пользователя из БД. rq.process_operation будет это обрабатывать.
    # user_id: int # Это поле будет взято из CurrentUserDep, а не из тела запроса.
    type: OperationType
    note: str = Field(..., max_length=256) # Обязательное поле, т.к. в models.py оно не nullable
    quantity: float = Field(..., description="Количество для операции (например, для приемки/отгрузки/инвентаризации)")
    from_location_id: Optional[int] = Field(None, description="Начальная локация для перемещения")
    to_location_id: Optional[int] = Field(None, description="Конечная локация для перемещения")

# OperationReadSchema будет использовать вашу текущую модель, без доп. полей
# Предполагается, что в вашей schemas.py уже есть корректная OperationReadSchema
# с полями id, item_id, user_id, type, note, created_at, created_by_id
# и relationships (item, user).

# Для журнала событий можно использовать OperationReadSchema или отдельную
# чтобы показать все связанные данные



# Зависимость для получения асинхронной сессии
async def get_session():
    async with async_session_factory() as session:
        try:
            yield session
        finally:
            await session.close()

SessionDep = Annotated[AsyncSession, Depends(get_session)]

# Зависимость для проверки авторизации пользователя
async def get_current_user(tg_id: int, session: SessionDep) -> UserORM:
    user = await rq.fetch_user_by_tg_id(tg_id, session)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не авторизован или неактивен.")
    return user

CurrentUserDep = Annotated[UserORM, Depends(get_current_user)]

# Зависимость для проверки роли администратора
async def get_current_admin_user(current_user: CurrentUserDep) -> UserORM:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав. Требуется роль администратора.")
    return current_user

CurrentAdminUserDep = Annotated[UserORM, Depends(get_current_admin_user)]

@asynccontextmanager
async def lifespan(app_: FastAPI):
    async with async_engine.begin() as conn:
        # await conn.run_sync(Base.metadata.drop_all) # Закомментировано
        await conn.run_sync(Base.metadata.create_all)
    print("Backend initialized and tables created.")
    yield

app = FastAPI(title="DiplomSklad", lifespan=lifespan)

origins = [
    "https://diplomsklad-ee2d3.web.app",
    "https://potential-broccoli-x5w54v7q7j9hvpwq-8000.app.github.dev",
    "https://web.telegram.org",
    "https://telegram.org",
    "https://*.telegram.org",
    "https://oauth.telegram.org",
    "http://localhost:8000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Эндпоинты для настройки и инициализации ---
@app.post("/setup_database")
async def setup_database_endpoint(session: SessionDep):
    """
    Создает таблицы в базе данных и вставляет тестовых пользователей.
    """
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    user1 = UserORM(tg_id=732334353, username="admin_user", role=UserRole.admin, is_active=True)
    user2 = UserORM(tg_id=1345214313, username="worker_user", role=UserRole.worker, is_active=True)
    session.add_all([user1, user2])
    await session.commit()

    return {"ok": True, "message": "Database setup complete and test users inserted."}

# --- Эндпоинты для пользователей (Users) ---

@app.post("/api/register", response_model=UserReadSchema)
async def register_user_endpoint(registration_data: UserCreateSchema, session: SessionDep):
    """
    Регистрация нового пользователя.
    """
    try:
        new_user = await rq.register_new_user(registration_data, session)
        await session.commit()
        return new_user
    except HTTPException as e:
        await session.rollback()
        raise e
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Внутренняя ошибка сервера: {e}")

@app.post("/api/check_admin_password")
async def check_admin_password_endpoint(password_data: Dict[str, str]):
    """
    Проверка пароля администратора (не использует БД).
    """
    password = password_data.get("password")
    ADMIN_PASSWORD = os.environ.get("ADMIN_REGISTRATION_PASSWORD")
    if password == ADMIN_PASSWORD:
        return {"status": "ok"}
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Неверный пароль администратора.")

@app.get("/api/users/{tg_id}", response_model=UserReadSchema)
async def get_user_by_tg_id(tg_id: int, session: SessionDep, current_user: CurrentUserDep):
    """
    Получение информации о пользователе по Telegram ID.
    (Доступно только для текущего авторизованного пользователя или администратора)
    """
    if current_user.tg_id != tg_id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав для просмотра информации о другом пользователе.")

    user = await rq.fetch_user_by_tg_id(tg_id, session)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    return rq.serialize_user(user)

@app.get("/api/users", response_model=List[UserReadSchema])
async def get_all_users_endpoint(session: SessionDep, current_admin: CurrentAdminUserDep):
    """
    Получение списка всех пользователей (только для администраторов).
    """
    users = await rq.get_all_users(session)
    return users

@app.put("/api/users/{user_id}", response_model=UserReadSchema)
async def update_user_endpoint(user_id: int, user_data: UserUpdateSchema, session: SessionDep, current_admin: CurrentAdminUserDep):
    """
    Обновление информации о пользователе по ID (только для администраторов).
    """
    updated_user = await rq.update_user(user_id, user_data, session)
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    await session.commit()
    return updated_user

@app.delete("/api/users/{user_id}", response_model=DeleteResponseSchema)
async def delete_user_endpoint(user_id: int, session: SessionDep, current_admin: CurrentAdminUserDep):
    """
    Удаление пользователя по ID (только для администраторов).
    """
    try:
        deleted = await rq.delete_user(user_id, session)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
        await session.commit()
        return {"message": f"Пользователь {user_id} удален.", "id": user_id}
    except HTTPException as e:
        await session.rollback()
        raise e
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Внутренняя ошибка сервера: {e}")

# --- Эндпоинты для товаров (Items) ---

@app.get("/api/items/scan/{code}", response_model=Dict[str, Any])
async def scan_item_endpoint(code: str, session: SessionDep, current_user: CurrentUserDep):
    """
    Сканирование товара по коду. Возвращает существующий товар или информацию для создания нового.
    """
    return await rq.scan_item_by_code(code, session)

@app.post("/api/items", response_model=ItemReadSchema)
async def create_item_endpoint(item_data: ItemCreateSchema, session: SessionDep, current_user: CurrentUserDep):
    """
    Создает новый товар в базе данных. Автоматически создает операцию "приемка".
    """
    try:
        # Передаем tg_id текущего пользователя для создания операции "приемка"
        new_item = await rq.create_item(item_data, current_user.tg_id, session)
        await session.commit()
        return new_item
    except HTTPException as e:
        await session.rollback()
        raise e
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Внутренняя ошибка сервера: {e}")

@app.get("/api/items", response_model=List[ItemReadSchema])
async def get_all_items_endpoint(session: SessionDep, current_user: CurrentUserDep):
    """
    Получение списка всех товаров.
    """
    items = await rq.get_items(session)
    return items

@app.get("/api/items/{item_id}", response_model=ItemReadSchema)
async def get_single_item_endpoint(item_id: int, session: SessionDep, current_user: CurrentUserDep):
    """
    Получение информации о товаре по ID.
    """
    item = await rq.get_item_by_id(item_id, session)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    return item

@app.put("/api/items/{item_id}", response_model=ItemReadSchema)
async def update_item_endpoint(item_id: int, item_data: ItemUpdateSchema, session: SessionDep, current_user: CurrentUserDep):
    """
    Обновление информации о товаре по ID.
    """
    updated_item = await rq.update_item(item_id, item_data, session)
    if not updated_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не найден")
    await session.commit()
    return updated_item

@app.delete("/api/items/{item_id}", response_model=DeleteResponseSchema)
async def delete_item_endpoint(item_id: int, session: SessionDep, current_user: CurrentUserDep):
    """
    Удаление товара по ID.
    """
    try:
        deleted = await rq.delete_item(item_id, session)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Товар не найден")
        await session.commit()
        return {"message": f"Товар {item_id} удален.", "id": item_id}
    except HTTPException as e:
        await session.rollback()
        raise e
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Внутренняя ошибка сервера: {e}")


@app.get("/api/users/{tg_id}/items", response_model=List[ItemReadSchema])
async def get_user_items_endpoint(tg_id: int, session: SessionDep, current_user: CurrentUserDep):
    """
    Получение всех товаров, связанных с пользователем по его Telegram ID.
    (ВНИМАНИЕ: В текущей ItemORM нет user_id. Эта функция вернет ВСЕ товары.)
    """
    if current_user.tg_id != tg_id and current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав для просмотра товаров другого пользователя.")
    return await rq.get_items_by_user_tg(tg_id, session)

# --- Эндпоинты для локаций (Locations) ---

@app.get("/api/locations", response_model=List[LocationReadSchema])
async def get_locations_endpoint(session: SessionDep, current_user: CurrentUserDep):
    """
    Получение списка всех локаций.
    """
    return await rq.fetch_all_locations(session)

@app.post("/api/locations", response_model=LocationReadSchema)
async def create_location_endpoint(location_data: LocationCreateSchema, session: SessionDep, current_user: CurrentUserDep):
    """
    Создание новой локации.
    """
    try:
        new_location = await rq.create_new_location(location_data, session)
        await session.commit()
        return new_location
    except HTTPException as e:
        await session.rollback()
        raise e
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Внутренняя ошибка сервера: {e}")

@app.put("/api/locations/{location_id}", response_model=LocationReadSchema)
async def update_location_endpoint(location_id: int, location_data: LocationUpdateSchema, session: SessionDep, current_user: CurrentUserDep):
    """
    Обновление информации о локации по ID.
    """
    updated_location = await rq.update_existing_location(location_id, location_data, session)
    if not updated_location:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Локация не найдена")
    await session.commit()
    return updated_location

@app.delete("/api/locations/{location_id}", response_model=DeleteResponseSchema)
async def delete_location_endpoint(location_id: int, session: SessionDep, current_user: CurrentUserDep):
    """
    Удаление локации по ID.
    """
    try:
        deleted = await rq.delete_existing_location(location_id, session)
        if not deleted:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Локация не найдена")
        await session.commit()
        return {"message": f"Локация {location_id} удалена.", "id": location_id}
    except HTTPException as e:
        await session.rollback()
        raise e
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Внутренняя ошибка сервера: {e}")

@app.get("/api/locations/{location_id}", response_model=LocationReadSchema)
async def get_single_location_endpoint(location_id: int, session: SessionDep, current_user: CurrentUserDep):
    """
    Получение информации о локации по ID.
    """
    location = await rq.fetch_location_by_id(location_id, session)
    if not location:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Локация не найдена")
    return rq.serialize_location(location)

# --- Эндпоинты для операций (Operations) ---

@app.post("/api/operations", response_model=OperationReadSchema)
async def create_operation_endpoint(
    op_data: AdaptedOperationCreateSchema, # Используем адаптированную схему для входных данных
    session: SessionDep,
    current_user: CurrentUserDep
):
    """
    Создание и обработка новой операции с товаром (отгрузка, приемка, инвентаризация, перемещение).
    Количество и локация (для перемещения) товара будут обновлены в ItemORM.
    """
    try:
        # Передаем tg_id текущего пользователя в функцию rq.process_operation
        result = await rq.process_operation(op_data, current_user.tg_id, session)
        await session.commit()
        return result
    except HTTPException as e:
        await session.rollback()
        raise e
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Внутренняя ошибка сервера: {e}")

@app.get("/api/operations/log", response_model=List[OperationReadSchema])
async def get_operations_log_endpoint(session: SessionDep, current_admin: CurrentAdminUserDep):
    """
    Получение журнала всех операций (только для администраторов).
    """
    operations = await rq.get_all_operations(session)
    return operations