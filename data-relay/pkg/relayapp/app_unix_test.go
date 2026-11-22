//go:build unix

package relayapp

import (
	"crypto/ed25519"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestIDRejectsNonPrivateLinkState(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "profile")
	if err := os.Mkdir(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	key := filepath.Join(directory, "link.key")
	seed := [ed25519.SeedSize]byte{1}
	if err := os.WriteFile(key, seed[:], 0o600); err != nil {
		t.Fatal(err)
	}
	check := func(want string) {
		t.Helper()
		err := Run(t.Context(), []string{"id", "--data-dir", directory}, io.Discard, io.Discard)
		if err == nil || !strings.Contains(err.Error(), want) {
			t.Fatalf("id = %v, want %q", err, want)
		}
	}
	if err := os.Chmod(directory, 0o750); err != nil {
		t.Fatal(err)
	}
	check("data directory permissions must exclude group and other users")
	if err := os.Chmod(directory, 0o700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(key, 0o640); err != nil {
		t.Fatal(err)
	}
	check("identity file permissions must exclude group and other users")
	if err := os.Rename(key, filepath.Join(directory, "seed")); err != nil {
		t.Fatal(err)
	}
	if err := os.Symlink("seed", key); err != nil {
		t.Fatal(err)
	}
	check("identity must be a regular private file")
}
