from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.orm import DeclarativeBase, MappedAsDataclass
from sqlalchemy.sql import Delete, Select, Update


class Base(MappedAsDataclass, DeclarativeBase):
    @classmethod
    def insert(cls) -> Insert:
        return Insert(cls)

    @classmethod
    def select(cls, *fields) -> Select:
        if fields:
            return select(*fields)
        return select(cls)

    @classmethod
    def update(cls) -> Update:
        return update(cls)

    @classmethod
    def delete(cls) -> Delete:
        return delete(cls)
