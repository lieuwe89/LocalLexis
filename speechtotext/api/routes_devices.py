from dataclasses import asdict
from fastapi import APIRouter

from speechtotext.devices import list_inputs

router = APIRouter()


@router.get("/devices")
def get_devices(include_all: bool = False) -> list[dict]:
    return [asdict(d) for d in list_inputs(include_all=include_all)]
