import os
from typing import List, Dict, Any, Optional

from fastapi import HTTPException
from sqlalchemy import select, update, delete, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload # Для загрузки связанных объектов

# Импортируем МОДЕЛИ из вашего НОВОГО проекта
from models import (
    UserORM, ItemORM, LocationORM, OperationORM,
    OperationType, UserRole
)
from database import async_session_factory # Ваш async_session_factory
# Импортируем СХЕМЫ из вашего НОВОГО проекта
from schemas import (
    UserCreateSchema, UserReadSchema, UserUpdateSchema,
    ItemCreateSchema, ItemReadSchema, ItemUpdateSchema,
    OperationCreateSchema, OperationReadSchema,
    LocationCreateSchema, LocationReadSchema, LocationUpdateSchema,
    OrmBaseModel
     # Для журнала событий
)

# --- Вспомогательные функции для сериализации ---
# Важно: Здесь предполагается, что ваши Read-схемы в schemas.py настроены
# для включения связанных объектов (например, ItemReadSchema имеет location: LocationReadSchema)

def serialize_user(user: UserORM) -> UserReadSchema:
    return UserReadSchema.model_validate(user)

def serialize_item(item: ItemORM) -> ItemReadSchema:
    return ItemReadSchema.model_validate(item)

def serialize_location(location: LocationORM) -> LocationReadSchema:
    return LocationReadSchema.model_validate(location)

def serialize_operation(operation: OperationORM) -> OperationReadSchema:
    return OperationReadSchema.model_validate(operation)

# --- Функции взаимодействия с БД ---

async def fetch_user_by_tg_id(tg_id: int, session: AsyncSession) -> Optional[UserORM]:
    user = await session.scalar(select(UserORM).where(UserORM.tg_id == tg_id))
    return user

async def get_items_by_user_tg(tg_id: int, session: AsyncSession) -> List[ItemReadSchema]:
    # Так как в ItemORM нет user_id, мы не можем получить товары "пользователя".
    # Если эта функция должна была отображать все товары, то так и оставляем.
    # Если она должна показывать товары, которые пользователь как-то "создал" или "связан",
    # то для этого в ItemORM должно быть поле user_id (ForeignKey).
    # В текущей реализации, она возвращает ВСЕ товары.
    user = await session.scalar(select(UserORM).where(UserORM.tg_id == tg_id))
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")

    items_query = select(ItemORM).options(selectinload(ItemORM.location))
    items = await session.scalars(items_query)
    return [serialize_item(item) for item in items]


async def scan_item_by_code(code: str, session: AsyncSession) -> Dict[str, Any]:
    # Загружаем связанную локацию
    item = await session.scalar(
        select(ItemORM)
        .options(selectinload(ItemORM.location))
        .where(ItemORM.code == code)
    )
    if item:
        return {"status": "exists", "item": serialize_item(item)}
    else:
        return {"status": "not_found", "item_code": code}


async def create_item(item_data: ItemCreateSchema, user_tg_id: int, session: AsyncSession) -> ItemReadSchema:
    try:
        existing_item = await session.scalar(select(ItemORM).where(ItemORM.code == item_data.code))
        if existing_item:
            raise HTTPException(status_code=400, detail="Товар с таким кодом уже существует.")

        location = await session.scalar(select(LocationORM).where(LocationORM.id == item_data.location_id))
        if not location:
            raise HTTPException(status_code=400, detail="Указанная локация не найдена.")

        # Получаем объект пользователя, который создает товар
        user_creator = await fetch_user_by_tg_id(user_tg_id, session)
        if not user_creator:
            raise HTTPException(status_code=400, detail="Пользователь, создающий товар, не найден.")


        new_item = ItemORM(
            code=item_data.code,
            name=item_data.name,
            weight=item_data.weight,
            quantity=item_data.quantity,
            description=item_data.description,
            location_id=item_data.location_id,
        )
        session.add(new_item)
        await session.flush() # Получаем ID нового товара

        # Создаем операцию "приемка" для нового товара, так как "добавление нового товара = приемка"
        new_operation = OperationORM(
            item_id=new_item.id,
            user_id=user_creator.id, # Кто совершил операцию (пользователь, создавший товар)
            type=OperationType.receive,
            note=f"Первичная приемка при добавлении нового товара. Количество: {item_data.quantity}",
            created_by_id=user_creator.id # Кто создал запись операции
        )
        session.add(new_operation)

        await session.flush()
        await session.refresh(new_item, attribute_names=['location']) # Обновляем с загрузкой связанной локации
        return serialize_item(new_item)
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Ошибка базы данных при создании товара. Возможно, дублирующиеся данные.")
    except Exception as e:
        await session.rollback()
        raise

async def get_items(session: AsyncSession) -> List[ItemReadSchema]:
    items_query = select(ItemORM).options(selectinload(ItemORM.location))
    items = await session.scalars(items_query)
    return [serialize_item(item) for item in items]

async def get_item_by_id(item_id: int, session: AsyncSession) -> Optional[ItemReadSchema]:
    item = await session.scalar(
        select(ItemORM)
        .options(selectinload(ItemORM.location))
        .where(ItemORM.id == item_id)
    )
    if item:
        return serialize_item(item)
    return None

async def update_item(item_id: int, item_data: ItemUpdateSchema, session: AsyncSession) -> Optional[ItemReadSchema]:
    item = await session.scalar(select(ItemORM).where(ItemORM.id == item_id))
    if not item:
        return None

    update_dict = item_data.model_dump(exclude_unset=True)

    if 'location_id' in update_dict and update_dict['location_id'] is not None:
        location = await session.scalar(select(LocationORM).where(LocationORM.id == update_dict['location_id']))
        if not location:
            raise HTTPException(status_code=400, detail="Указанная локация не найдена.")

    for key, value in update_dict.items():
        if hasattr(item, key):
            setattr(item, key, value)

    await session.flush()
    await session.refresh(item, attribute_names=['location'])
    return serialize_item(item)

async def delete_item(item_id: int, session: AsyncSession) -> bool:
    item = await session.scalar(select(ItemORM).where(ItemORM.id == item_id))
    if not item:
        return False
    associated_operations_count = await session.scalar(select(func.count(OperationORM.id)).where(OperationORM.item_id == item_id))
    if associated_operations_count > 0:
        raise HTTPException(status_code=400, detail="Невозможно удалить товар, так как с ним связаны операции. Сначала удалите или переназначьте их.")

    await session.delete(item)
    await session.flush()
    return True

async def create_new_location(location_data: LocationCreateSchema, session: AsyncSession) -> LocationReadSchema:
    try:
        existing_location = await session.scalar(
            select(LocationORM).where(LocationORM.name == location_data.name)
        )
        if existing_location:
            raise HTTPException(status_code=400, detail="Локация с таким именем уже существует.")
        new_location = LocationORM(
            name=location_data.name,
            description=location_data.description
        )
        session.add(new_location)
        await session.flush()
        await session.refresh(new_location)
        return serialize_location(new_location)
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Ошибка базы данных при создании локации. Возможно, дублирующиеся данные.")
    except Exception as e:
        await session.rollback()
        raise

async def update_existing_location(location_id: int, location_data: LocationUpdateSchema, session: AsyncSession) -> Optional[LocationReadSchema]:
    location = await session.scalar(select(LocationORM).where(LocationORM.id == location_id))
    if not location:
        return None

    update_dict = location_data.model_dump(exclude_unset=True)

    for key, value in update_dict.items():
        if hasattr(location, key):
            setattr(location, key, value)

    await session.flush()
    await session.refresh(location)
    return serialize_location(location)

async def delete_existing_location(location_id: int, session: AsyncSession) -> bool:
    location = await session.scalar(select(LocationORM).where(LocationORM.id == location_id))
    if not location:
        return False
    associated_items_count = await session.scalar(select(func.count(ItemORM.id)).where(ItemORM.location_id == location_id))
    # В вашей OperationORM нет from_location_id или to_location_id, поэтому эти проверки невозможны напрямую
    # Если вы хотите, чтобы операции "перемещение" препятствовали удалению локации,
    # нужно будет добавить поля from_location_id и to_location_id в OperationORM.
    # В текущей реализации, удаление локации, в которой есть товары, заблокировано.
    if associated_items_count > 0:
        raise HTTPException(status_code=400, detail="Невозможно удалить локацию, так как с ней связаны товары. Сначала переместите их.")
    await session.delete(location)
    await session.flush()
    return True

async def fetch_location_by_id(location_id: int, session: AsyncSession) -> Optional[LocationORM]:
    location = await session.scalar(select(LocationORM).where(LocationORM.id == location_id))
    return location

async def fetch_all_locations(session: AsyncSession) -> List[LocationReadSchema]:
    locations = await session.scalars(select(LocationORM))
    return [serialize_location(loc) for loc in locations]

async def process_operation(op_data: OperationCreateSchema, user_tg_id: int, session: AsyncSession) -> OperationReadSchema:
    # Ищем пользователя по tg_id, который совершает операцию
    user_performer = await fetch_user_by_tg_id(user_tg_id, session)
    if not user_performer:
        raise HTTPException(status_code=404, detail="Пользователь, совершающий операцию, не найден.")

    item = await session.scalar(select(ItemORM).where(ItemORM.id == op_data.item_id))
    if not item:
        raise HTTPException(status_code=404, detail="Товар не найден.")

    # Логика изменения количества ItemORM.quantity
    if op_data.type == OperationType.receive:
        item.quantity += op_data.quantity
    elif op_data.type == OperationType.ship:
        if item.quantity < op_data.quantity:
            raise HTTPException(status_code=400, detail="Недостаточно товара для отгрузки.")
        item.quantity -= op_data.quantity
    elif op_data.type == OperationType.inventory:
        item.quantity = op_data.quantity # Устанавливаем новое количество
    elif op_data.type == OperationType.move:
        if not op_data.to_location_id: # Для перемещения to_location_id обязателен
            raise HTTPException(status_code=400, detail="Для операции 'перемещение' необходима конечная локация (to_location_id).")
        if item.location_id == op_data.to_location_id:
            raise HTTPException(status_code=400, detail="Товар уже находится в указанной конечной локации.")
        # Проверяем, что from_location_id соответствует текущей локации товара, если указан
        if op_data.from_location_id and item.location_id != op_data.from_location_id:
            raise HTTPException(status_code=400, detail="Начальная локация операции перемещения не совпадает с текущей локацией товара.")

        # Обновляем локацию товара
        target_location = await session.scalar(select(LocationORM).where(LocationORM.id == op_data.to_location_id))
        if not target_location:
            raise HTTPException(status_code=404, detail=f"Конечная локация с ID {op_data.to_location_id} не найдена.")
        item.location_id = op_data.to_location_id


    operation = OperationORM(
        item_id=item.id,
        user_id=user_performer.id, # ID пользователя из БД
        type=op_data.type,
        note=op_data.note,
        created_by_id=user_performer.id # Кто создал запись операции (тот же, кто совершил)
        # Поля quantity, from_location_id, to_location_id НЕ будут сохранены в OperationORM,
        # так как их нет в вашей models.py. Они влияют только на ItemORM.
    )
    session.add(operation)

    await session.flush() # Flush для получения operation.id
    # Для сериализации operation, загружаем связанные объекты.
    # Обратите внимание, что to_location и from_location могут быть None в OperationReadSchema,
    # если их нет в вашей OperationORM. Здесь они не будут загружены, так как их нет в OperationORM.
    await session.refresh(operation, attribute_names=['item', 'user'])
    # Важно также обновить item, чтобы его актуальное состояние было доступно, если нужно
    await session.refresh(item, attribute_names=['location']) # Чтобы ItemReadSchema получил обновленную локацию

    return serialize_operation(operation)

async def get_all_operations(session: AsyncSession) -> List[OperationReadSchema]:
    # Загружаем связанные объекты для полноценного отображения в журнале
    # Item загружаем с его Location, User загружаем
    operations_query = select(OperationORM).options(
        selectinload(OperationORM.item).selectinload(ItemORM.location),
        selectinload(OperationORM.user) # Пользователь, который совершил
        # created_by_id есть, но нет связи created_by в OperationORM, если не добавили
        # Если хотите иметь доступ к created_by, нужно добавить relationship в OperationORM
    ).order_by(OperationORM.created_at.desc())
    operations = await session.scalars(operations_query)
    return [serialize_operation(op) for op in operations]

async def register_new_user(registration_data: UserCreateSchema, session: AsyncSession) -> UserReadSchema:
    try:
        existing_user = await session.scalar(select(UserORM).where(UserORM.tg_id == registration_data.tg_id))
        if existing_user:
            raise HTTPException(
                status_code=409,
                detail="Пользователь с таким Telegram ID уже зарегистрирован."
            )
        new_user = UserORM(
            tg_id=registration_data.tg_id,
            username=registration_data.username,
            role=registration_data.role,
            is_active=True
        )
        session.add(new_user)
        await session.flush()
        await session.refresh(new_user)
        print(f"Зарегистрирован новый пользователь: {new_user.__dict__}")
        return serialize_user(new_user)
    except IntegrityError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail="Ошибка базы данных при регистрации пользователя. Возможно, дублирующиеся данные.")
    except Exception as e:
        await session.rollback()
        raise

async def get_all_users(session: AsyncSession) -> List[UserReadSchema]:
    users = await session.scalars(select(UserORM))
    return [serialize_user(user) for user in users]

async def update_user(user_id: int, user_data: UserUpdateSchema, session: AsyncSession) -> Optional[UserReadSchema]:
    user = await session.scalar(select(UserORM).where(UserORM.id == user_id))
    if not user:
        return None

    update_dict = user_data.model_dump(exclude_unset=True)

    for key, value in update_dict.items():
        if hasattr(user, key):
            setattr(user, key, value)

    await session.flush()
    await session.refresh(user)
    return serialize_user(user)

async def delete_user(user_id: int, session: AsyncSession) -> bool:
    user = await session.scalar(select(UserORM).where(UserORM.id == user_id))
    if not user:
        return False

    associated_operations = await session.scalar(select(func.count(OperationORM.id)).where(OperationORM.user_id == user_id))
    # В ItemORM нет user_id, поэтому нет прямой связи для проверки
    # associated_items = await session.scalar(select(func.count(ItemORM.id)).where(ItemORM.user_id == user_id))


    if associated_operations > 0: # Снял проверку на items
        raise HTTPException(status_code=400, detail="Невозможно удалить пользователя, так как с ним связаны операции. Сначала удалите или переназначьте их.")

    await session.delete(user)
    await session.flush()
    return True