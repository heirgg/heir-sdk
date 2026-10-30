package heir

import (
	"context"
	"errors"
	"testing"
)

func TestPageAllStopsWhenContextIsCanceled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	token := "next"
	page := newPage("body", []string{"first", "second"}, true, &token, func(context.Context, string) (*Page[string, string], error) {
		t.Fatal("canceled iterator fetched another page")
		return nil, nil
	})
	var items []string
	var gotError error
	for item, err := range page.All(ctx) {
		if err != nil {
			gotError = err
			break
		}
		items = append(items, item)
		cancel()
	}
	if len(items) != 1 || !errors.Is(gotError, context.Canceled) {
		t.Fatalf("items=%v error=%v", items, gotError)
	}
}

func TestPageAllStopsWithoutFetchingWhenConsumerBreaks(t *testing.T) {
	token := "next"
	page := newPage("body", []string{"first", "second"}, true, &token, func(context.Context, string) (*Page[string, string], error) {
		t.Fatal("consumer stopped but another page was fetched")
		return nil, nil
	})
	for _, err := range page.All(context.Background()) {
		if err != nil {
			t.Fatal(err)
		}
		break
	}
}

func TestPageAllPropagatesNextPageFailure(t *testing.T) {
	expected := errors.New("next page failed")
	token := "next"
	page := newPage("body", []string{"first"}, true, &token, func(context.Context, string) (*Page[string, string], error) { return nil, expected })
	var got error
	for _, err := range page.All(context.Background()) {
		if err != nil {
			got = err
		}
	}
	if !errors.Is(got, expected) {
		t.Fatalf("error=%v", got)
	}
}
