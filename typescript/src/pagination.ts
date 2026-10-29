/** What every paginated answer carries besides its rows. */
export interface PageBody {
  page: number;
  pageSize: number;
  hasMore: boolean;
  nextToken: string | null;
}

/**
 * One page of a list, with the whole answer in `body` and its rows in `items`. `next()` fetches the following page
 * with the same League, filters and page size, and iterating the page with `for await` walks its rows and then every
 * page after it:
 *
 * ```ts
 * for await (const roster of await league.rosters()) console.log(roster.name);
 * ```
 */
export class Page<Item, Body extends PageBody = PageBody> implements AsyncIterable<Item> {
  constructor(
    readonly body: Body,
    readonly items: readonly Item[],
    private readonly fetchNext: (nextToken: string) => Promise<Page<Item, Body>>
  ) {}

  get hasMore(): boolean {
    return this.body.hasMore && this.body.nextToken !== null;
  }

  get nextToken(): string | null {
    return this.body.nextToken;
  }

  private following: Promise<Page<Item, Body> | null> | undefined;

  /** The page after this one, or null at the end of the list. Fetched once; asking again returns the same page. */
  next(): Promise<Page<Item, Body> | null> {
    this.following ??= this.body.nextToken === null || !this.body.hasMore ? Promise.resolve(null) : this.fetchNext(this.body.nextToken).catch(error => { this.following = undefined; throw error; });
    return this.following;
  }

  async *[Symbol.asyncIterator](): AsyncIterator<Item> {
    let page: Page<Item, Body> | null = this;
    while (page) {
      yield* page.items;
      page = await page.next();
    }
  }
}
