import datetime
import enum
from typing import Annotated

from sqlalchemy import (
    TIMESTAMP,
    CheckConstraint,
    Column,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Boolean,
    Table,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base, str_256

intpk = Annotated[int, mapped_column(primary_key=True)]
created_at = Annotated[datetime.datetime, mapped_column(server_default=func.now())]
updated_at = Annotated[datetime.datetime, mapped_column(
        server_default=func.now(),
        onupdate=datetime.datetime.now,
    )]

class UserRole(enum.Enum):
    admin = "admin"
    worker = "worker"
class OperationType(enum.Enum):
    receive = "receive"
    move = "move"
    ship = "ship"
    inventory = "inventory"

class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[intpk]
    tg_id: Mapped[int] 
    username: Mapped[str_256 | None]
    last_login: Mapped[updated_at]
    role: Mapped[UserRole]
    is_active: Mapped[bool | None]
    created_at: Mapped[created_at]

    operations: Mapped[list["OperationORM"]] = relationship(
        back_populates="user"
        )



class ItemORM(Base):
    __tablename__ = "items"

    id: Mapped[intpk]
    code: Mapped[str_256]
    name: Mapped[str_256]
    weight: Mapped[int]
    quantity: Mapped[int]
    location_id: Mapped[int] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    description: Mapped[str_256]
    created_at: Mapped[created_at]

    location: Mapped["LocationORM"] = relationship(
        back_populates="items",
    )
    operations: Mapped[list["OperationORM"]] = relationship(
        back_populates="item"
    )


class LocationORM(Base):
    __tablename__ = "locations"

    id: Mapped[intpk]
    name: Mapped[str_256]
    description: Mapped[str_256]
    created_at: Mapped[created_at]

    items: Mapped[list["ItemORM"]] = relationship(
        back_populates="location",
    )


class OperationORM(Base):
    __tablename__ = "operations"

    id: Mapped[intpk]
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[OperationType]
    note: Mapped[str_256]
    created_at: Mapped[created_at]
    created_by_id: Mapped[int]

    item: Mapped["ItemORM"] = relationship(
        back_populates="operations",
    )
    user: Mapped["UserORM"] = relationship(
        back_populates="operations",
    )


