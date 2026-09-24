from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from app.engine.node_schemas import NODE_SCHEMAS

router = APIRouter(prefix="/api", tags=["node-types"])


class NodeTypeSchema(BaseModel):
    type: str
    label: str
    category: str
    params_schema: dict[str, Any]
    outputs: list[str]


@router.get("/node-types", response_model=list[NodeTypeSchema])
async def list_node_types() -> list[NodeTypeSchema]:
    return [
        NodeTypeSchema(
            type=node_type,
            label=schema.label,
            category=schema.category,
            params_schema=schema.params.model_json_schema(),
            outputs=schema.outputs,
        )
        for node_type, schema in NODE_SCHEMAS.items()
    ]