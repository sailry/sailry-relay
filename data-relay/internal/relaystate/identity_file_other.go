//go:build !unix

package relaystate

import "os"

func openIdentityKey(root *os.Root) (*os.File, error) {
	return root.Open(identityName)
}
