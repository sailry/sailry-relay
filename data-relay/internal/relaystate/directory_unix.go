//go:build unix

package relaystate

import (
	"os"
	"syscall"
)

func PrivateDirectory(path string) error {
	if err := os.MkdirAll(path, 0o700); err != nil {
		return err
	}
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return invalidProfile(path, "data directory must not be a symbolic link")
	}
	if info.Sys().(*syscall.Stat_t).Uid != uint32(os.Geteuid()) {
		return invalidProfile(path, "data directory must belong to the current user")
	}
	if info.Mode().Perm()&0o077 != 0 {
		return invalidProfile(path, "data directory permissions must exclude group and other users")
	}
	return nil
}
