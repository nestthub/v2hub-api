"""
Base repository providing common database operations.

This module provides a generic repository pattern implementation that can be
extended by specific repositories for type-safe database operations.
"""

from typing import Any, Generic, List, Optional, Type, TypeVar
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Base repository with common CRUD operations.
    
    Provides type-safe database operations that can be extended by
    specific model repositories.
    """
    
    def __init__(self, model: Type[ModelType], session: AsyncSession):
        """
        Initialize repository.
        
        Args:
            model: SQLAlchemy model class
            session: Async database session
        """
        self.model = model
        self.session = session
    
    async def get_by_id(self, id_value: Any) -> Optional[ModelType]:
        """
        Get model instance by primary key.
        
        Args:
            id_value: Primary key value
            
        Returns:
            Model instance or None if not found
        """
        return await self.session.get(self.model, id_value)
        
    async def get_by_pk(self, *pk_values) -> Optional[ModelType]:
        return await self.session.get(self.model, pk_values)
    
    async def get_all(self, limit: int = 100, offset: int = 0) -> List[ModelType]:
        """
        Get all model instances with pagination.
        
        Args:
            limit: Maximum number of records to return
            offset: Number of records to skip
            
        Returns:
            List of model instances
        """
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    
    async def get_all_by_field(
        self,
        field,
        value,
        limit: int | None = 100,
        offset: int = 0,
    ) -> list[ModelType]:
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            stmt = select(self.model).where(field.in_(value))
        else:
            stmt = select(self.model).where(field == value)
    
        if offset:
            stmt = stmt.offset(offset)
    
        if limit is not None:
            stmt = stmt.limit(limit)
    
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def create(self, **kwargs) -> ModelType:
        """
        Create a new model instance.
        
        Args:
            **kwargs: Model field values
            
        Returns:
            Created model instance
        """
        instance = self.model(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance
    
    async def update(self, instance: ModelType, **kwargs) -> ModelType:
        """
        Update model instance.
        
        Args:
            instance: Model instance to update
            **kwargs: Fields to update
            
        Returns:
            Updated model instance
        """
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance
    
    async def delete(self, instance: ModelType) -> None:
        """
        Delete model instance.
        
        Args:
            instance: Model instance to delete
        """
        await self.session.delete(instance)
        await self.session.flush()
    
    async def exists(self, **filters) -> bool:
        """
        Check if a record exists matching the filters.
        
        Args:
            **filters: Field filters (field_name=value)
            
        Returns:
            True if record exists, False otherwise
        """
        stmt = select(self.model)
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        
        stmt = stmt.limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None
    
    async def count(self, **filters) -> int:
        """
        Count records matching filters.
        
        Args:
            **filters: Field filters (field_name=value)
            
        Returns:
            Count of matching records
        """
        from sqlalchemy import func
        
        stmt = select(func.count()).select_from(self.model)
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        
        result = await self.session.execute(stmt)
        return result.scalar_one()
