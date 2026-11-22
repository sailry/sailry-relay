package peerrelay

import (
	"context"
	"errors"

	"github.com/libp2p/go-libp2p"
	"github.com/libp2p/go-libp2p/core/peer"
	"github.com/libp2p/go-libp2p/p2p/protocol/ping"
)

// Probe authenticates the relay PeerID and checks for a ping response.
func Probe(ctx context.Context, address string) error {
	relay, err := peer.AddrInfoFromString(address)
	if err != nil {
		return err
	}
	probe, err := libp2p.New(libp2p.NoListenAddrs, libp2p.DisableRelay(), libp2p.DisableMetrics())
	if err != nil {
		return err
	}
	defer probe.Close()
	if err := probe.Connect(ctx, *relay); err != nil {
		return err
	}
	scoped, cancel := context.WithCancel(ctx)
	defer cancel()
	select {
	case <-scoped.Done():
		return scoped.Err()
	case result, ok := <-ping.Ping(scoped, probe, relay.ID):
		if !ok {
			return errors.New("relay ping ended without a result")
		}
		return result.Error
	}
}
