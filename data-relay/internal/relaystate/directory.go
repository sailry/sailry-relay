package relaystate

import "fmt"

func invalidProfile(path, reason string) error {
	return fmt.Errorf("invalid profile %s: %s", path, reason)
}
