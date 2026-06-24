package sample

import (
	"fmt"
	"net/http"
)

// DefaultTimeout is the default request timeout.
const DefaultTimeout = 30

// MaxRetries controls the retry limit.
var MaxRetries = 3

// unexported constant (should not appear in exports)
const internalLimit = 100

// Config holds application configuration.
type Config struct {
	Host string
	Port int
}

// Handler defines the request handler interface.
type Handler interface {
	ServeHTTP(w http.ResponseWriter, r *http.Request)
}

// StringAlias is a named type.
type StringAlias string

// NewConfig creates a new Config with defaults.
func NewConfig(host string, port int) *Config {
	return &Config{Host: host, Port: port}
}

// unexported function (should not appear)
func helperFunc() {}

// Start launches the server.
func (c *Config) Start() error {
	fmt.Printf("Starting on %s:%d\n", c.Host, c.Port)
	return nil
}

// unexported method (should not appear)
func (c *Config) validate() bool {
	return c.Host != ""
}
