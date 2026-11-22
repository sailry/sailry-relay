//go:build !unix

package relayapp

import "os"

const relayFileReadFlags = os.O_RDONLY
