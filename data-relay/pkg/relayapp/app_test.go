package relayapp

import (
	"bytes"
	"context"
	"crypto/ed25519"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/libp2p/go-libp2p/core/crypto"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/sailry/sailry-relay/data-relay/internal/relaystate"
)

func TestIDUsesExistingLinkIdentity(t *testing.T) {
	directory := filepath.Join(t.TempDir(), "profile")
	args := []string{"id", "--data-dir", directory}
	var output bytes.Buffer
	if err := Run(t.Context(), args, &output, io.Discard); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("id before profile creation: %v", err)
	}
	if _, err := os.Stat(directory); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("id created the profile directory: %v", err)
	}
	if err := relaystate.PrivateDirectory(directory); err != nil {
		t.Fatal(err)
	}
	if err := Run(t.Context(), args, &output, io.Discard); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("id before identity creation: %v", err)
	}
	if output.Len() != 0 {
		t.Fatalf("id printed output without an identity: %q", output.String())
	}

	seed := [ed25519.SeedSize]byte{1}
	if err := os.WriteFile(filepath.Join(directory, "link.key"), seed[:], 0o600); err != nil {
		t.Fatal(err)
	}
	key, err := crypto.UnmarshalEd25519PrivateKey(ed25519.NewKeyFromSeed(seed[:]))
	if err != nil {
		t.Fatal(err)
	}
	want, err := peer.IDFromPrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	for range 2 {
		if err := Run(t.Context(), args, &output, io.Discard); err != nil {
			t.Fatal(err)
		}
		if got := output.String(); got != want.String()+"\n" {
			t.Fatalf("id output = %q, want %s", got, want)
		}
		output.Reset()
	}
}

func TestServeAccessMode(t *testing.T) {
	seed := [ed25519.SeedSize]byte{1}
	key, err := crypto.UnmarshalEd25519PrivateKey(ed25519.NewKeyFromSeed(seed[:]))
	if err != nil {
		t.Fatal(err)
	}
	device, err := peer.IDFromPrivateKey(key)
	if err != nil {
		t.Fatal(err)
	}
	directory := filepath.Join(t.TempDir(), "relay")
	args := []string{"serve", "--data-dir", directory, "--listen", "/ip4/127.0.0.1/tcp/0"}
	for _, extra := range [][]string{nil, {"--public", "--allow", device.String()}} {
		if err := Run(t.Context(), append(args, extra...), io.Discard, io.Discard); err == nil || !strings.Contains(err.Error(), "exactly one access mode") {
			t.Fatalf("invalid access mode %v: %v", extra, err)
		}
	}
	if _, err := os.Stat(directory); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("invalid access mode created relay state: %v", err)
	}

	ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	defer cancel()
	var output bytes.Buffer
	report := relayOutput(func(data []byte) (int, error) {
		defer cancel()
		return output.Write(data)
	})
	if err := Run(ctx, append(args, "--public"), report, io.Discard); err != nil {
		t.Fatal(err)
	}
	address, err := peer.AddrInfoFromString(strings.TrimSpace(output.String()))
	if err != nil || address.ID == "" || len(address.Addrs) != 1 {
		t.Fatalf("invalid public relay address %q: %v", output.String(), err)
	}
	var identity bytes.Buffer
	if err := Run(t.Context(), []string{"id", "--data-dir", directory}, &identity, io.Discard); err != nil {
		t.Fatal(err)
	}
	if strings.TrimSpace(identity.String()) != address.ID.String() {
		t.Fatal("public relay did not persist the advertised identity")
	}
}

type relayOutput func([]byte) (int, error)

func (write relayOutput) Write(data []byte) (int, error) { return write(data) }
