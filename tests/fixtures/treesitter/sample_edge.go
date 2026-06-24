package sample

import (
	"context"
	"sync"
)

// List is a generic container.
type List[T comparable] struct {
	items []T
	mu    sync.Mutex
}

// Pair holds two values of different types.
type Pair[K comparable, V any] struct {
	Key   K
	Value V
}

// Stringer can convert itself to a string.
type Stringer interface {
	String() string
}

type (
	// UserID is a typed identifier.
	UserID int64
	// GroupID is a typed identifier.
	GroupID int64
)

// Node has an embedded field.
type Node struct {
	sync.Mutex
	Value int
	Left  *Node
	Right *Node
}

// Map transforms a slice using a generic function.
func Map[T, U any](items []T, fn func(T) U) []U {
	result := make([]U, len(items))
	for i, v := range items {
		result[i] = fn(v)
	}
	return result
}

// Filter returns matching elements.
func Filter[T any](items []T, pred func(T) bool) []T {
	var out []T
	for _, v := range items {
		if pred(v) {
			out = append(out, v)
		}
	}
	return out
}

// Swap returns two values in reverse order.
func Swap[A, B any](a A, b B) (B, A) {
	return b, a
}

var (
	// GlobalRegistry is the shared registry.
	GlobalRegistry = make(map[string]any)
	// DefaultCtx is the default context.
	DefaultCtx = context.Background()
)

// unexported generic (should not appear)
func merge[T any](a, b []T) []T {
	return append(a, b...)
}
