from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def reject_explicit_null(model: BaseModel, *fields: str) -> None:
    """PATCH: поле можно не присылать, но нельзя прислать null — колонка NOT NULL (иначе IntegrityError, а не 422)."""
    for name in fields:
        if name in model.model_fields_set and getattr(model, name) is None:
            raise ValueError(f"Поле «{name}» не может быть null")


class UserShort(ORMModel):
    id: int
    username: str
    display_name: str


class DepartmentShort(ORMModel):
    id: int
    name: str


class ComputerShort(ORMModel):
    id: int
    name: str
    tier: str
    is_virtual: bool
    cpu: str | None
    ram_gb: int | None
    storage: str | None
    gpu: str | None
