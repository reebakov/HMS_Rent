from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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
