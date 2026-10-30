"""What the routes need, wired once by create_app() and read per request."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated

from fastapi import Depends, Request

from askfootage.application.library import IdFactory, Library
from askfootage.application.recordings import FootageSource
from askfootage.application.search import Interpreter


@dataclass(frozen=True, slots=True)
class ApiContext:
    """The stores, clock, interpreter and limits the routes hand to the use cases."""

    library: Library
    interpreter: Interpreter
    footage: FootageSource
    today: Callable[[], date]
    utc_now: Callable[[], datetime]
    make_id: IdFactory
    max_upload_bytes: int


def get_context(request: Request) -> ApiContext:
    """The ApiContext of the app serving this request."""
    context = request.app.state.context
    assert isinstance(context, ApiContext)
    return context


Context = Annotated[ApiContext, Depends(get_context)]
"""Route parameter type that injects the ApiContext."""
