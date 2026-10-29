"""Pages of a list, and walking them."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Generic, TypeVar

ItemT = TypeVar("ItemT")
BodyT = TypeVar("BodyT")


class Page(Generic[ItemT, BodyT]):
    """One page of a list: its rows in `items` and the whole answer in `body`.

    `next()` fetches the following page with the same League, filters and page size, and iterating a page walks its
    rows and then every page after it::

        for roster in league.rosters():
            print(roster.name)
    """

    def __init__(
        self,
        body: BodyT,
        items: list[ItemT],
        has_more: bool,
        next_token: str | None,
        fetch_next: Callable[[str], Page[ItemT, BodyT]],
    ) -> None:
        self.body = body
        self.items = items
        self._has_more = has_more
        self.next_token = next_token
        self._fetch_next = fetch_next

    @property
    def has_more(self) -> bool:
        return self._has_more and self.next_token is not None

    def next(self) -> Page[ItemT, BodyT] | None:
        """The page after this one, or None at the end of the list."""
        if not self.has_more or self.next_token is None:
            return None
        return self._fetch_next(self.next_token)

    def __iter__(self) -> Iterator[ItemT]:
        page: Page[ItemT, BodyT] | None = self
        while page is not None:
            yield from page.items
            page = page.next()

    def __repr__(self) -> str:
        return f"Page(items={len(self.items)}, has_more={self.has_more})"


class AsyncPage(Generic[ItemT, BodyT]):
    """One page of a list, from an async client. `await page.next()` fetches the following page, and `async for`
    walks this page's rows and every page after it."""

    def __init__(
        self,
        body: BodyT,
        items: list[ItemT],
        has_more: bool,
        next_token: str | None,
        fetch_next: Callable[[str], Awaitable[AsyncPage[ItemT, BodyT]]],
    ) -> None:
        self.body = body
        self.items = items
        self._has_more = has_more
        self.next_token = next_token
        self._fetch_next = fetch_next

    @property
    def has_more(self) -> bool:
        return self._has_more and self.next_token is not None

    async def next(self) -> AsyncPage[ItemT, BodyT] | None:
        """The page after this one, or None at the end of the list."""
        if not self.has_more or self.next_token is None:
            return None
        return await self._fetch_next(self.next_token)

    async def __aiter__(self) -> AsyncIterator[ItemT]:
        page: AsyncPage[ItemT, BodyT] | None = self
        while page is not None:
            for item in page.items:
                yield item
            page = await page.next()

    def __repr__(self) -> str:
        return f"AsyncPage(items={len(self.items)}, has_more={self.has_more})"
