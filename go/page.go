package heir

import (
	"context"
	"iter"
)

// Page is one page of a list: its rows in Items and the whole answer in Body. Next fetches the following page with
// the same League, filters and page size, and All walks this page's rows and every page after it:
//
//	page, err := league.Rosters(ctx, nil)
//	for roster, err := range page.All(ctx) {
//		if err != nil { return err }
//		fmt.Println(roster.Name)
//	}
type Page[Item any, Body any] struct {
	Items []Item
	Body  Body

	hasMore   bool
	nextToken string
	fetchNext func(ctx context.Context, nextToken string) (*Page[Item, Body], error)
}

// HasMore reports whether a page follows this one.
func (p *Page[Item, Body]) HasMore() bool { return p.hasMore && p.nextToken != "" }

// NextToken continues the list in a later process; it is empty at the end.
func (p *Page[Item, Body]) NextToken() string { return p.nextToken }

// Next returns the page after this one, or nil at the end of the list.
func (p *Page[Item, Body]) Next(ctx context.Context) (*Page[Item, Body], error) {
	if !p.HasMore() {
		return nil, nil
	}
	return p.fetchNext(ctx, p.nextToken)
}

// All yields this page's rows and then every page after it, stopping at the first error.
func (p *Page[Item, Body]) All(ctx context.Context) iter.Seq2[Item, error] {
	return func(yield func(Item, error) bool) {
		for page := p; page != nil; {
			for _, item := range page.Items {
				if !yield(item, nil) {
					return
				}
			}
			next, err := page.Next(ctx)
			if err != nil {
				var zero Item
				yield(zero, err)
				return
			}
			page = next
		}
	}
}

func newPage[Item any, Body any](body Body, items []Item, hasMore bool, nextToken *string, fetchNext func(ctx context.Context, nextToken string) (*Page[Item, Body], error)) *Page[Item, Body] {
	page := &Page[Item, Body]{Items: items, Body: body, hasMore: hasMore, fetchNext: fetchNext}
	if nextToken != nil {
		page.nextToken = *nextToken
	}
	return page
}
